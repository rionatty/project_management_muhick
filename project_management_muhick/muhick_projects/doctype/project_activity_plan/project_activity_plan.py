# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Activity plan: the project's schedule, its milestones and the items each milestone needs. Approved
COO -> Finance -> General Manager.

The schedule is one outline, laid out as the business's activity schedule: ID, task name, duration in working
days, start, finish and predecessors (25,28 or 6SS or 25FS+2 days), worked out as a scheduling tool does (see
calc.work_out_schedule). A row is a subtask of the row whose ID it names as its Group Task ID, and a row with
subtasks is a group task; Type on each row says which it is. Its top rows are the milestones, past a lone row
that only wraps them such as the project's name.

Milestones, group tasks and subtasks are standard ERPNext Tasks in the same tree: a milestone is a top-level group
task of the project, so the Task tree, the Gantt chart and timesheets work as usual. Milestone names come from the
shared milestone list (ERPNext's Task Type),
and each project milestone task carries its milestone in the standard Type field. The Milestones table follows
the schedule and holds what only a milestone has: its weight, valuation and claim. Standard sets of milestones
and activities come from a Project Template. Approval creates or updates the tasks. A later change to dates,
weights or valuations is a revision: a new plan that states why the schedule moved, while the first approved
dates stay on each task as its baseline. The items each milestone needs stay on the plan; the budget and the
milestone material requests are taken from them.
"""

import base64
import io
import re
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate, strip_html, today, validate_email_address

from project_management_muhick.muhick_projects import estimate
from project_management_muhick.muhick_projects.utils import ensure_milestone
from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils import calc

# plan row field -> Task field
PHASE_FIELDS = {
	"planned_start": "exp_start_date",
	"planned_end": "exp_end_date",
	"weight": "task_weight",
	"planned_valuation": "muhick_planned_valuation",
	"planned_claim_date": "muhick_planned_claim_date",
	"is_billing_milestone": "muhick_is_billing_milestone",
}
ACTIVITY_FIELDS = {"start_date": "exp_start_date", "end_date": "exp_end_date"}
# what a schedule row carries into a revision
SCHEDULE_FIELDS = (
	"row_id", "parent_row", "outline_level", "row_type", "subject", "duration", "start_date", "end_date", "predecessors", "responsibility",
	"phase_name", "is_summary", "task_weight", "description", "task",
)
RESPONSIBILITIES = ("Muhick", "Client", "Subcontractor", "Joint")
EXCEL_COLUMNS = (
	("row_id", "ID"), ("parent_row", "Group Task ID"), ("subject", "Task Name"), ("duration", "Duration"), ("start_date", "Start"),
	("end_date", "Finish"), ("predecessors", "Predecessors"), ("responsibility", "Responsibility"),
)
# the headings a schedule's columns go by, here and in a scheduling tool's export
HEADINGS = {
	"id": "row_id", "grouptaskid": "parent_row", "grouptask": "parent_row", "level": "outline_level", "outlinelevel": "outline_level",
	"wbs": "wbs", "taskname": "subject", "name": "subject",
	"task": "subject", "activity": "subject", "duration": "duration", "days": "duration", "start": "start_date", "startdate": "start_date",
	"finish": "end_date", "finishdate": "end_date", "end": "end_date", "enddate": "end_date", "predecessors": "predecessors",
	"dependson": "predecessors", "responsibility": "responsibility",
}
DATE_FORMATS = (
	"%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y", "%d-%b-%y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y",
)


class ProjectActivityPlan(Document):
	def validate(self):
		self.check_single_open_plan()
		self.work_out_schedule()
		self.validate_phases()
		self.validate_items()
		self.set_summary()
		if self.revision_of:
			if not (self.revision_reason or "").strip() or not self.change_driver:
				frappe.throw(_("A revision must state what drove the change and the reason."))
			self.check_dropped_tasks()

	def before_insert(self):
		if self.revision_of:
			self.revision_no = (frappe.db.get_value("Project Activity Plan", self.revision_of, "revision_no") or 0) + 1

	def check_single_open_plan(self):
		draft = frappe.db.get_value(
			"Project Activity Plan", {"project": self.project, "docstatus": 0, "name": ("!=", self.name or "")}, "name"
		)
		if draft:
			frappe.throw(_("Project {0} already has an activity plan awaiting approval: {1}.").format(self.project, draft))
		current = frappe.db.get_value(
			"Project Activity Plan", {"project": self.project, "docstatus": 1, "is_current": 1}, "name"
		)
		if current and self.revision_of != current:
			frappe.throw(
				_("Project {0} has an approved activity plan ({1}). Use Revise Plan on it to change the schedule.").format(
					self.project, current
				)
			)

	def work_out_schedule(self):
		"""The schedule's rows from their durations and predecessors, and the Milestones table following its
		milestones. What only that table holds stays with each milestone's name. A plan with no schedule keeps the
		milestones typed in."""
		if not self.activities:
			return
		rows = sorted(self.activities, key=lambda row: row.idx or 0)
		for row in rows:
			row.subject = (row.subject or "").strip()
			if not row.subject:
				frappe.throw(_("Schedule row {0}: give the task name.").format(row.idx))
			if row.task and frappe.db.get_value("Task", row.task, "project") != self.project:
				frappe.throw(_("Schedule row {0}: task {1} belongs to another project.").format(row.idx, row.task))
		try:
			order, worked = _work_out(rows, _first_day(self.project, self.plan_date))
		except calc.ScheduleError as error:
			frappe.throw(_schedule_message(error))
		self.activities[:] = [rows[place] for place in order]
		names, milestones = {}, []
		for position, (row, out) in enumerate(zip(self.activities, worked)):
			if out["milestone"] == position:
				names[position] = ensure_milestone(row.subject)
				if names[position] in [name for name, _row in milestones]:
					frappe.throw(_("Schedule row {0}: {1} appears twice as a milestone.").format(out["id"], names[position]))
				milestones.append((names[position], row))
			row.update(
				{
					"idx": position + 1, "row_id": out["id"], "parent_row": out["group"], "outline_level": out["level"], "row_type": out["kind"],
					"predecessors": out["predecessors"], "start_date": out["start"], "end_date": out["end"], "duration": out["duration"], "is_summary": cint(out["summary"]),
					"phase_name": names.get(out["milestone"]), "responsibility": row.responsibility or RESPONSIBILITIES[0],
				}
			)
		held = {row.phase_name: row for row in self.phases}
		phases = []
		for position, (name, row) in enumerate(milestones, 1):
			phase = held.get(name) or self.append("phases", {"phase_name": name})
			phase.update({"idx": position, "planned_start": row.start_date, "planned_end": row.end_date})
			phases.append(phase)
		self.set("phases", phases)

	def validate_phases(self):
		if not self.phases:
			frappe.throw(_("Add the schedule's rows first."))
		names = set()
		for row in self.phases:
			row.phase_name = (row.phase_name or "").strip()
			if row.phase_name in names:
				frappe.throw(_("Milestones row {0}: {1} appears twice.").format(row.idx, row.phase_name))
			names.add(row.phase_name)
			if getdate(row.planned_end) < getdate(row.planned_start):
				frappe.throw(_("Milestones row {0}: Planned End is before Planned Start.").format(row.idx))
			if row.phase:
				task = frappe.db.get_value("Task", row.phase, ["project", "is_group"], as_dict=True)
				if not task or task.project != self.project or not task.is_group:
					frappe.throw(_("Milestones row {0}: {1} is not a milestone of project {2}.").format(row.idx, row.phase, self.project))
		self.total_weight = sum(flt(r.weight) for r in self.phases)
		if self.total_weight and abs(self.total_weight - 100) > 0.01:
			frappe.throw(_("Milestone weights must total 100% (they total {0}%).").format(f"{self.total_weight:g}"))

	def validate_items(self):
		phases = {r.phase_name for r in self.phases}
		seen = set()
		for row in self.items:
			if row.phase_name not in phases:
				frappe.throw(_("Items Required row {0}: {1} is not a milestone of this plan.").format(row.idx, row.phase_name))
			if flt(row.qty) <= 0:
				frappe.throw(_("Items Required row {0}: enter the quantity of {1}.").format(row.idx, row.item_code))
			if (row.phase_name, row.item_code) in seen:
				frappe.throw(_("Items Required row {0}: {1} is listed twice for {2}.").format(row.idx, row.item_code, row.phase_name))
			seen.add((row.phase_name, row.item_code))

	def set_summary(self):
		self.plan_start = min(getdate(r.planned_start) for r in self.phases)
		self.plan_end = max(getdate(r.planned_end) for r in self.phases)
		self.total_planned_valuation = sum(flt(r.planned_valuation) for r in self.phases)
		contract = frappe.db.get_value(
			"Project", self.project, ["muhick_contract_value", "muhick_approved_variations"], as_dict=True
		)
		self.contract_value = flt(contract.muhick_contract_value) + flt(contract.muhick_approved_variations) if contract else 0
		if self.contract_value and self.total_planned_valuation > self.contract_value + 0.5:
			frappe.msgprint(
				_("Planned valuations ({0}) are more than the contract value ({1}).").format(
					frappe.format_value(self.total_planned_valuation, "Currency"),
					frappe.format_value(self.contract_value, "Currency"),
				),
				indicator="orange",
			)

	def kept_tasks(self) -> set:
		return {r.phase for r in self.phases if r.phase} | {r.task for r in self.activities if r.task}

	def dropped_tasks(self, fields=("name",)):
		"""Tasks an approved plan created that this revision leaves out."""
		return frappe.get_all(
			"Task",
			filters={
				"project": self.project,
				"muhick_activity_plan": ("is", "set"),
				"status": ("!=", "Cancelled"),
				"name": ("not in", list(self.kept_tasks()) or [""]),
			},
			fields=list(fields),
			order_by="is_group asc, lft desc",  # what is under a task before the task
		)

	def check_dropped_tasks(self):
		"""A milestone or activity left out of a revision is cancelled, which is only allowed while it is untouched."""
		for t in self.dropped_tasks(("name", "subject", "progress", "muhick_billing_status")):
			if flt(t.progress) or t.muhick_billing_status:
				frappe.throw(_("{0} has progress recorded and cannot be removed from the plan.").format(t.subject))

	# ------------------------------------------------------------------ approval
	def on_submit(self):
		self.extend_project_dates()
		frappe.flags.muhick_applying_plan = True
		try:
			if self.revision_of:
				# cancelled first, so a shortened milestone does not trip over an activity that is leaving
				cancel_tasks(self.dropped_tasks())
			phases = self.apply_phases()
			self.apply_activities(phases)
		finally:
			frappe.flags.muhick_applying_plan = False
		frappe.get_doc("Project", self.project).update_project()
		project_api.update_progress(self.project)
		# budget lines made from the bid's estimate had only a stage until now
		estimate.link_budget_phases(self.project)
		frappe.db.set_value(
			"Project Activity Plan",
			{"project": self.project, "is_current": 1, "name": ("!=", self.name)},
			"is_current",
			0,
		)
		self.db_set("is_current", 1)
		frappe.db.set_value("Project", self.project, "muhick_activity_plan", self.name)

	def extend_project_dates(self):
		"""ERPNext refuses a task dated outside its project, so the project covers the plan."""
		start, end = frappe.db.get_value("Project", self.project, ["expected_start_date", "expected_end_date"])
		dates = [getdate(self.plan_start), getdate(self.plan_end)]
		values = {}
		if not start or getdate(start) > min(dates):
			values["expected_start_date"] = min(dates)
		if not end or getdate(end) < max(dates):
			values["expected_end_date"] = max(dates)
		if values:
			frappe.db.set_value("Project", self.project, values)

	def apply_phases(self) -> dict:
		names = {}
		for row in self.phases:
			task = frappe.get_doc("Task", row.phase) if row.phase else frappe.new_doc("Task")
			task.update(
				{
					"subject": row.phase_name, "type": row.phase_name, "project": self.project, "is_group": 1,
					"muhick_activity_plan": self.name,
				}
			)
			for source, target in PHASE_FIELDS.items():
				task.set(target, row.get(source))
			if row.description:
				task.description = row.description
			save_task(task, row.planned_start, row.planned_end)
			if row.phase != task.name:
				row.db_set("phase", task.name, update_modified=False)
			names[row.phase_name] = task.name
		return names

	def apply_activities(self, phases):
		"""The schedule's rows as tasks in the same tree: a milestone is the task apply_phases made for it, a group task a
		group task under its own group task, a subtask a task; rows above the milestones only wrap them. A longer
		subtask counts for more in its group's progress unless it is given a weight. Finish-to-start predecessors become
		the task's dependencies, ERPNext reading those as "cannot be completed before"; any other kind only sets dates."""
		rows = sorted(self.activities, key=lambda row: row.idx or 0)
		levels = [cint(row.outline_level) for row in rows]
		parents = calc.outline_parents(levels)
		milestones = set(calc.outline_milestones(levels))
		tasks = {}
		for position, row in enumerate(rows):
			if not row.phase_name:
				continue
			if position in milestones:
				tasks[position] = phases[row.phase_name]
			else:
				task = frappe.get_doc("Task", row.task) if row.task else frappe.new_doc("Task")
				task.update(
					{
						"subject": row.subject, "project": self.project, "parent_task": tasks[parents[position]],
						"is_group": 1 if row.is_summary or task.is_group else 0, "muhick_activity_plan": self.name,
						"task_weight": flt(row.task_weight) or cint(row.duration),
					}
				)
				for source, target in ACTIVITY_FIELDS.items():
					task.set(target, row.get(source))
				if row.description:
					task.description = row.description
				save_task(task, row.start_date, row.end_date)
				tasks[position] = task.name
			if row.task != tasks[position]:
				row.db_set("task", tasks[position], update_modified=False)
		for position, name in tasks.items():
			needed = [
				tasks[other - 1]
				for other, kind, lag in calc.parse_predecessors(rows[position].predecessors)
				if kind == "FS" and lag >= 0 and other - 1 in tasks
			]
			task = frappe.get_doc("Task", name)
			# ERPNext has a task depend on those under it too
			under = frappe.get_all("Task", filters={"parent_task": name}, pluck="name")
			if {d.task for d in task.get("depends_on") or []} != {*needed, *under}:
				task.set("depends_on", [{"task": t} for t in dict.fromkeys([*needed, *under])])
				task.flags.from_project = True
				task.flags.ignore_permissions = True
				task.save()

	def on_cancel(self):
		if self.revision_of:
			frappe.throw(_("An approved revision cannot be cancelled. Raise a new revision to change the plan again."))
		tasks = frappe.get_all(
			"Task",
			filters={"project": self.project, "muhick_activity_plan": self.name, "status": ("!=", "Cancelled")},
			fields=["name", "progress", "muhick_billing_status"],
			order_by="is_group asc, lft desc",
		)
		if any(flt(t.progress) or t.muhick_billing_status for t in tasks):
			frappe.throw(_("Progress has been recorded against this plan. Revise the plan instead of cancelling it."))
		frappe.flags.muhick_applying_plan = True
		try:
			cancel_tasks(tasks)
		finally:
			frappe.flags.muhick_applying_plan = False
		self.db_set("is_current", 0)
		if frappe.db.get_value("Project", self.project, "muhick_activity_plan") == self.name:
			frappe.db.set_value("Project", self.project, "muhick_activity_plan", None)


def save_task(task, start, end):
	if task.status == "Cancelled":
		task.status = "Open"  # back in the plan
	if not task.get("muhick_baseline_start"):
		task.muhick_baseline_start, task.muhick_baseline_end = start, end
	task.flags.from_project = True  # the project is rolled up once, after all tasks are saved
	task.flags.ignore_permissions = True
	task.save()


def cancel_tasks(tasks):
	"""Cancel rather than delete: a task may already carry timesheets, requests or claims."""
	for t in tasks:
		task = frappe.get_doc("Task", t.name)
		task.status = "Cancelled"
		task.flags.from_project = True
		task.flags.ignore_permissions = True
		task.save()


# ------------------------------------------------------------------ working out a schedule
def _work_out(rows, first_day) -> tuple:
	"""Rows in the outline their Group Task IDs make, worked out: the places they come from, and what each comes to."""
	inputs = [
		{
			"id": cint(row.get("row_id")), "group": cint(row.get("parent_row")), "duration": cint(row.get("duration")),
			"start": _date(row.get("start_date")), "end": _date(row.get("end_date")), "predecessors": row.get("predecessors"),
		}
		for row in rows
	]
	order, levels = calc.outline_from_groups(inputs)
	return order, calc.work_out_schedule([{**inputs[place], "level": levels[place]} for place in order], first_day)


def _first_day(project, plan_date=None):
	"""Where a schedule row with nothing else to go on starts."""
	return getdate((frappe.db.get_value("Project", project, "expected_start_date") if project else None) or plan_date or nowdate())


def _schedule_message(error) -> str:
	if error.kind == "format":
		return _("Schedule row {0}: predecessor {1} should read like 25, 6SS or 25FS+2 days.").format(error.row, error.text)
	if error.kind == "unknown":
		return _("Schedule row {0}: predecessor {1} is not in the schedule.").format(error.row, error.text)
	if error.kind == "group":
		return _("Schedule row {0}: group task {1} is not in the schedule.").format(error.row, error.text)
	if error.kind == "group-loop":
		return _("Schedule row {0} ends up under itself through its group tasks.").format(error.row)
	return _("Schedule row {0} ends up depending on itself through its predecessors.").format(error.row)


@frappe.whitelist()
def get_worked_schedule(rows, project: str | None = None, plan_date: str | None = None) -> dict:
	"""The schedule's rows as they work out now, for the form to show before saving: {rows} in their new order, each with
	the place it comes from, or {error}."""
	frappe.has_permission("Project Activity Plan", "read", throw=True)
	try:
		order, worked = _work_out(frappe.parse_json(rows), _first_day(project, plan_date))
	except calc.ScheduleError as error:
		return {"error": _schedule_message(error)}
	return {
		"rows": [
			{
				"from": place, "row_id": out["id"], "parent_row": out["group"], "outline_level": out["level"], "row_type": out["kind"],
				"predecessors": out["predecessors"], "start_date": out["start"], "end_date": out["end"], "duration": out["duration"], "is_summary": cint(out["summary"]),
			}
			for place, out in zip(order, worked)
		]
	}


# ------------------------------------------------------------------ the approved schedule as it stands
@frappe.whitelist()
def get_live_schedule(plan: str) -> dict:
	"""An approved plan's rows, where their tasks stand now and whom to ask for a milestone's sign-off."""
	doc = frappe.get_doc("Project Activity Plan", plan)
	doc.check_permission("read")
	tasks = frappe.get_all(
		"Task",
		filters={"name": ("in", [row.task for row in doc.activities if row.task] or [""])},
		fields=["name", "status", "progress", "muhick_signoff_requested_on", "muhick_client_signed_off_on"],
	)
	customer = frappe.db.get_value("Project", doc.project, "customer")
	return {
		"rows": [row.as_dict() for row in doc.activities],
		"live": {task.name: task for task in tasks},
		"client_email": frappe.db.get_value("Customer", customer, "email_id") if customer else None,
	}


@frappe.whitelist()
def request_signoff(task: str, email: str, message: str):
	"""Email the client for a milestone's sign-off, and note when it was asked for."""
	doc = frappe.get_doc("Task", task)
	doc.check_permission("write")
	validate_email_address(email, throw=True)
	frappe.sendmail(
		recipients=[email], subject=_("Sign-off requested: {0}").format(doc.subject), message=message, reference_doctype="Task", reference_name=task
	)
	doc.db_set("muhick_signoff_requested_on", today())


@frappe.whitelist()
def record_signoff(task: str, signed_on: str):
	"""The date the client confirmed a milestone."""
	doc = frappe.get_doc("Task", task)
	doc.check_permission("write")
	doc.db_set("muhick_client_signed_off_on", getdate(signed_on))


# ------------------------------------------------------------------ to and from Excel
@frappe.whitelist()
def download_schedule(name: str | None = None):
	"""A workbook of the saved schedule, or an empty one, to prepare in Excel and upload."""
	from openpyxl import Workbook
	from openpyxl.styles import Font

	frappe.has_permission("Project Activity Plan", "read", throw=True)
	doc = frappe.get_doc("Project Activity Plan", name) if name else None
	if doc:
		doc.check_permission("read")
	book = Workbook()
	sheet = book.active
	sheet.title = "Activity Schedule"
	sheet.append([heading for _field, heading in EXCEL_COLUMNS])
	for cell in sheet[1]:
		cell.font = Font(bold=True)
	for row in sorted(doc.activities, key=lambda r: r.idx) if doc else []:
		sheet.append([row.get(field) for field, _heading in EXCEL_COLUMNS])
	for column, width in zip("ABCDEFGH", (6, 7, 60, 10, 12, 12, 24, 16)):
		sheet.column_dimensions[column].width = width
	sheet.freeze_panes = "A2"
	out = io.BytesIO()
	book.save(out)
	frappe.response["filename"] = f"{name or _('Activity Schedule')}.xlsx"
	frappe.response["filecontent"] = out.getvalue()
	frappe.response["type"] = "binary"


@frappe.whitelist()
def read_schedule(filename: str, content: str) -> dict:
	"""The rows of an uploaded schedule, from the sheet whose heading row names the task and its duration or start:
	the workbook given out here, or a scheduling tool's export. A row's level is its Level or Outline Level column, else
	the depth of its WBS, else how far its name is indented. A task's dates and predecessors are read as such tools
	write them: 7 days, Fri 21/03/25, 25FS+2 days."""
	frappe.has_permission("Project Activity Plan", "create", throw=True)
	for _sheet, rows in estimate._read_sheets(filename, base64.b64decode(content.split(",", 1)[-1])):
		for at, row in enumerate(rows):
			columns = {HEADINGS[_heading_key(value)]: i for i, value in reversed(list(enumerate(row))) if _heading_key(value) in HEADINGS}
			if "subject" in columns and ("duration" in columns or "start_date" in columns):
				found = _schedule_rows(rows[at + 1 :], columns)
				return {"rows": found, "errors": [] if found else [_("The file's heading row has no rows of tasks under it.")]}
	return {"rows": [], "errors": [_("No schedule found. A sheet needs a heading row naming Task Name and Duration or Start, as in the Excel file downloaded from here.")]}


def _schedule_rows(rows, columns) -> list:
	def cell(row, field):
		at = columns.get(field)
		return row[at] if at is not None and at < len(row) else None

	out = []
	for row in rows:
		name = cell(row, "subject")
		subject = str(name).strip() if name not in (None, "") else ""
		if not subject:
			continue
		out.append(
			{
				"row_id": cint(_number_text(cell(row, "row_id"))), "subject": subject, "outline_level": _level(row, name, cell),
				"duration": _duration(cell(row, "duration")), "start_date": _schedule_date(cell(row, "start_date")),
				"end_date": _schedule_date(cell(row, "end_date")), "predecessors": _number_text(cell(row, "predecessors")),
				"responsibility": next((r for r in RESPONSIBILITIES if r.lower() == str(cell(row, "responsibility") or "").strip().lower()), RESPONSIBILITIES[0]),
			}
		)
	# an export says a row's level, not its group task: the row above it at a lesser level
	for place, row in enumerate(out):
		row["row_id"] = row["row_id"] or place + 1
	if "parent_row" in columns:
		for row, raw in zip(out, (r for r in rows if str(cell(r, "subject") or "").strip())):
			row["parent_row"] = cint(_number_text(cell(raw, "parent_row")))
	else:
		lowest = min((row["outline_level"] for row in out), default=0)
		for row, parent in zip(out, calc.outline_parents([row["outline_level"] for row in out])):
			row["outline_level"] -= lowest
			row["parent_row"] = out[parent]["row_id"] if parent is not None else 0
	return out


def _level(row, name, cell) -> int:
	level = cell(row, "outline_level")
	if level not in (None, ""):
		return cint(_number_text(level))
	wbs = str(cell(row, "wbs") or "").strip().strip(".")
	if wbs:
		return wbs.count(".")
	return (len(str(name)) - len(str(name).lstrip())) // 3


def _heading_key(value) -> str:
	return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _number_text(value) -> str:
	"""A cell as text, a number as Excel holds one (25.0) as 25."""
	if isinstance(value, float) and value == int(value):
		value = int(value)
	return str(value).strip() if value not in (None, "") else ""


def _duration(value) -> int:
	"""Working days from a cell as scheduling tools write it: 7 days, 1 day, 14d, 2 wks, 7."""
	found = re.match(r"\s*(\d+(?:\.\d+)?)\s*(w)?", str(value or "").lower())
	return round(float(found.group(1)) * (5 if found.group(2) else 1)) if found else 0


def _schedule_date(value):
	"""A date from a cell: a date, an Excel number, or text such as Fri 21/03/25. None when it reads as neither."""
	if isinstance(value, (datetime, date)):
		return getdate(value)
	if isinstance(value, (int, float)):
		return (datetime(1899, 12, 30) + timedelta(days=value)).date() if value else None
	text = re.sub(r"\s+\d{1,2}:\d{2}.*$", "", re.sub(r"^[A-Za-z]{3,9},?\s+(?=\d)", "", str(value or "").strip()))
	for pattern in DATE_FORMATS:
		try:
			return datetime.strptime(text, pattern).date()
		except ValueError:
			continue
	return None


# ------------------------------------------------------------------ loading a schedule into a plan
@frappe.whitelist()
def load_phases(project: str, project_template: str | None = None) -> dict:
	"""A schedule for a new plan: from a Project Template, or from the project's own tasks (for example those ERPNext
	created from the project's template), or else from the stages in the project's BOQ, with the items each stage needs."""
	frappe.has_permission("Project Activity Plan", "create", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	if project_template:
		return _from_template(project, project_template)
	loaded = _from_project(project)
	return loaded if loaded["phases"] else _from_boq(project)


def _outline(tasks, depends) -> list:
	"""Schedule rows for tasks ({name, parent, ...the row's fields}) in their tree, each naming its group task; a
	task's predecessors are those it depends on other than the tasks under it."""
	by_name = {t["name"]: t for t in tasks}
	under = {}
	for t in tasks:
		under.setdefault(t["parent"] if t["parent"] in by_name else None, []).append(t)
	rows, ids = [], {}

	def walk(parent, level):
		for t in under.get(parent, []):
			ids[t["name"]] = len(rows) + 1
			rows.append({"row_id": ids[t["name"]], "parent_row": ids.get(parent, 0), "outline_level": level, **{k: v for k, v in t.items() if k not in ("name", "parent")}})
			rows[-1]["_name"] = t["name"]
			walk(t["name"], level + 1)

	walk(None, 0)
	for row in rows:
		name = row.pop("_name")
		row["predecessors"] = ",".join(str(ids[d]) for d in depends.get(name, []) if d in ids and by_name[d]["parent"] != name)
	return rows


def _from_template(project, template):
	start = getdate(frappe.db.get_value("Project", project, "expected_start_date") or nowdate())
	tasks = [frappe.get_doc("Task", row.task) for row in frappe.get_doc("Project Template", template).tasks]
	by_name = {t.name: t for t in tasks}
	phases, rows = [], []
	for t in tasks:
		begin = add_days(start, int(t.start or 0))
		end = add_days(begin, max(int(t.duration or 0), 0))
		top = t.parent_task not in by_name
		name = ensure_milestone(t.type or t.subject) if top else t.subject
		if top:
			phases.append({"phase_name": name, "planned_start": begin, "planned_end": end, "weight": t.task_weight})
		rows.append(
			{"name": t.name, "parent": t.parent_task, "subject": name, "start_date": begin, "end_date": end, "task_weight": None if top else t.task_weight}
		)
	activities = _outline(rows, {t.name: [d.task for d in t.depends_on] for t in tasks})
	_fit_phases(phases, activities)
	return {"phases": phases, "activities": activities}


def _from_project(project):
	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "status": ("!=", "Cancelled")},
		fields=["name", "subject", "type", "parent_task", "is_group", "exp_start_date", "exp_end_date", "task_weight", "description"],
		order_by="exp_start_date asc, lft asc",
	)
	tasks = [t for t in tasks if t.parent_task or t.is_group]
	phases, rows = [], []
	for t in tasks:
		top = not t.parent_task
		name = ensure_milestone(t.type or t.subject) if top else t.subject
		if top:
			phases.append(
				{
					"phase": t.name, "phase_name": name, "planned_start": _date(t.exp_start_date), "planned_end": _date(t.exp_end_date),
					"weight": t.task_weight, "description": strip_html(t.description or ""),
				}
			)
		rows.append(
			{
				"name": t.name, "parent": t.parent_task, "task": t.name, "subject": name, "start_date": _date(t.exp_start_date),
				"end_date": _date(t.exp_end_date), "task_weight": None if top else t.task_weight,
			}
		)
	depends = {}
	for d in frappe.get_all("Task Depends On", filters={"parent": ("in", [t.name for t in tasks] or [""])}, fields=["parent", "task"]):
		depends.setdefault(d.parent, []).append(d.task)
	activities = _outline(rows, depends)
	_fit_phases(phases, activities)
	return {"phases": phases, "activities": activities}


def _from_boq(project):
	"""One milestone per stage in the BOQ, in the order the stages first appear, and per stage the
	BOQ items with their quantities added up."""
	boq = frappe.db.get_value("Project", project, "muhick_boq") or frappe.db.get_value(
		"Project BOQ", {"project": project, "docstatus": ("<", 2)}, "name", order_by="creation desc"
	)
	needs = {}
	for row in frappe.get_all(
		"Project BOQ Item",
		filters={"parent": boq or "", "milestone": ("is", "set"), "item_code": ("is", "set")},
		fields=["milestone", "item_code", "qty"],
		order_by="idx asc",
	):
		needs[(row.milestone, row.item_code)] = needs.get((row.milestone, row.item_code), 0) + flt(row.qty)
	stages = list(dict.fromkeys(stage for stage, _item in needs))
	phases = [{"phase_name": stage} for stage in stages]
	activities = [{"row_id": i, "outline_level": 0, "subject": stage} for i, stage in enumerate(stages, 1)]
	_fit_phases(phases, activities)
	items = [{"phase_name": stage, "item_code": item, "qty": qty} for (stage, item), qty in needs.items()]
	return {"phases": phases, "activities": activities, "items": items}


def _fit_phases(phases, activities):
	"""Give undated rows a date, until the schedule is worked out on saving."""
	today_date = getdate(nowdate())
	for a in activities:
		a["start_date"] = a.get("start_date") or today_date
		a["end_date"] = a.get("end_date") or a["start_date"]
	for p in phases:
		p["planned_start"] = p.get("planned_start") or today_date
		p["planned_end"] = p.get("planned_end") or p["planned_start"]


def _date(value):
	return getdate(value) if value else None


@frappe.whitelist()
def make_revision(source_name: str):
	"""A new draft plan with the approved schedule, milestones and items, ready to be changed. Tasks added by hand under
	its milestones since come in under them."""
	source = frappe.get_doc("Project Activity Plan", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or not source.is_current:
		frappe.throw(_("Only the current approved plan can be revised."))
	doc = frappe.new_doc("Project Activity Plan")
	doc.update({"project": source.project, "company": source.company, "revision_of": source.name})
	for p in source.phases:
		doc.append(
			"phases",
			{
				**{f: p.get(f) for f in ("phase", "phase_name", "planned_start", "planned_end", "weight", "planned_valuation", "planned_claim_date", "is_billing_milestone", "description")},
				"previous_start": p.planned_start,
				"previous_end": p.planned_end,
			},
		)
	rows = [{f: row.get(f) for f in SCHEDULE_FIELDS} for row in sorted(source.activities, key=lambda r: r.idx)]
	milestones = {p.phase: p.phase_name for p in source.phases if p.phase}
	others = frappe.get_all(
		"Task",
		filters={
			"project": source.project, "parent_task": ("in", list(milestones) or [""]), "status": ("!=", "Cancelled"),
			"name": ("not in", [row["task"] for row in rows if row["task"]] or [""]),
		},
		fields=["name", "subject", "parent_task", "exp_start_date", "exp_end_date", "task_weight"],
		order_by="exp_start_date asc, lft asc",
	)
	for t in others:
		name = milestones[t.parent_task]
		last = max(i for i, row in enumerate(rows) if row["phase_name"] == name)
		group = next(row for row in rows if row["phase_name"] == name)
		rows.insert(
			last + 1,
			{
				"task": t.name, "subject": t.subject, "parent_row": group["row_id"], "phase_name": name, "start_date": _date(t.exp_start_date),
				"end_date": _date(t.exp_end_date), "task_weight": t.task_weight, "responsibility": RESPONSIBILITIES[0],
			},
		)
	for row in rows:
		doc.append("activities", row)
	for item in source.items:
		doc.append(
			"items",
			{f: item.get(f) for f in ("phase_name", "item_code", "item_name", "qty", "uom", "required_by", "remarks")},
		)
	return doc
