# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Activity plan: the project's phases, the activities in each phase and the items each phase
needs. Approved COO -> Finance -> General Manager.

Phases and activities are standard ERPNext Tasks: a phase is a group task of the project and its
activities are its child tasks, so the Task tree, the Gantt chart and timesheets work as usual.
Standard phase lists come from a Project Template. Approval creates or updates the tasks. A later
change to dates, weights or valuations is a revision: a new plan that states why the schedule
moved, while the first approved dates stay on each task as its baseline. The items each phase
needs stay on the plan; the budget and the phase material requests are taken from them.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, nowdate, strip_html

from project_management_muhick.overrides import project as project_api

# plan row field -> Task field
PHASE_FIELDS = {
	"planned_start": "exp_start_date",
	"planned_end": "exp_end_date",
	"weight": "task_weight",
	"planned_valuation": "muhick_planned_valuation",
	"planned_claim_date": "muhick_planned_claim_date",
	"is_billing_milestone": "muhick_is_billing_milestone",
}
ACTIVITY_FIELDS = {"start_date": "exp_start_date", "end_date": "exp_end_date", "task_weight": "task_weight"}


class ProjectActivityPlan(Document):
	def validate(self):
		self.check_single_open_plan()
		self.validate_phases()
		self.validate_activities()
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

	def validate_phases(self):
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

	def validate_activities(self):
		phases = {r.phase_name: r for r in self.phases}
		subjects = set()
		for row in self.activities:
			row.subject = (row.subject or "").strip()
			if row.subject in subjects:
				frappe.throw(_("Activities row {0}: {1} appears twice.").format(row.idx, row.subject))
			subjects.add(row.subject)
			phase = phases.get(row.phase_name)
			if not phase:
				frappe.throw(_("Activities row {0}: {1} is not a milestone of this plan.").format(row.idx, row.phase_name))
			start, end = getdate(row.start_date), getdate(row.end_date)
			if end < start:
				frappe.throw(_("Activities row {0}: End is before Start.").format(row.idx))
			# ERPNext keeps a child task inside its parent's dates
			if start < getdate(phase.planned_start) or end > getdate(phase.planned_end):
				frappe.throw(
					_("Activities row {0}: {1} must fall within its milestone {2} ({3} to {4}).").format(
						row.idx, row.subject, row.phase_name, phase.planned_start, phase.planned_end
					)
				)
			if row.task and frappe.db.get_value("Task", row.task, "project") != self.project:
				frappe.throw(_("Activities row {0}: task {1} belongs to another project.").format(row.idx, row.task))
		for row in self.activities:
			dependency = (row.depends_on_subject or "").strip()
			if dependency and (dependency == row.subject or dependency not in subjects):
				frappe.throw(_("Activities row {0}: {1} is not another activity of this plan.").format(row.idx, dependency))

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
			order_by="is_group asc",  # activities before their phase
		)

	def check_dropped_tasks(self):
		"""A phase or activity left out of a revision is cancelled, which is only allowed while it is untouched."""
		for t in self.dropped_tasks(("name", "subject", "progress", "muhick_billing_status")):
			if flt(t.progress) or t.muhick_billing_status:
				frappe.throw(_("{0} has progress recorded and cannot be removed from the plan.").format(t.subject))

	# ------------------------------------------------------------------ approval
	def on_submit(self):
		self.extend_project_dates()
		frappe.flags.muhick_applying_plan = True
		try:
			if self.revision_of:
				# cancelled first, so a shortened phase does not trip over an activity that is leaving
				cancel_tasks(self.dropped_tasks())
			phases = self.apply_phases()
			self.apply_activities(phases)
		finally:
			frappe.flags.muhick_applying_plan = False
		frappe.get_doc("Project", self.project).update_project()
		project_api.update_progress(self.project)
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
			task.update({"subject": row.phase_name, "project": self.project, "is_group": 1, "muhick_activity_plan": self.name})
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
		tasks = {}
		for row in self.activities:
			task = frappe.get_doc("Task", row.task) if row.task else frappe.new_doc("Task")
			task.update(
				{"subject": row.subject, "project": self.project, "parent_task": phases[row.phase_name], "muhick_activity_plan": self.name}
			)
			for source, target in ACTIVITY_FIELDS.items():
				task.set(target, row.get(source))
			if row.description:
				task.description = row.description
			save_task(task, row.start_date, row.end_date)
			if row.task != task.name:
				row.db_set("task", task.name, update_modified=False)
			tasks[row.subject] = task
		for row in self.activities:
			dependency = (row.depends_on_subject or "").strip()
			if not dependency:
				continue
			task, needed = tasks[row.subject], tasks[dependency].name
			if needed not in [d.task for d in task.get("depends_on") or []]:
				task.append("depends_on", {"task": needed})
				task.flags.from_project = True
				task.save()

	def on_cancel(self):
		if self.revision_of:
			frappe.throw(_("An approved revision cannot be cancelled. Raise a new revision to change the plan again."))
		tasks = frappe.get_all(
			"Task",
			filters={"project": self.project, "muhick_activity_plan": self.name, "status": ("!=", "Cancelled")},
			fields=["name", "progress", "muhick_billing_status"],
			order_by="is_group asc",
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


# ------------------------------------------------------------------ loading phases into a plan
@frappe.whitelist()
def load_phases(project: str, project_template: str | None = None) -> dict:
	"""Phases and activities for a new plan: from a Project Template, or from the project's own
	phase tasks (for example those ERPNext created from the project's template)."""
	frappe.has_permission("Project Activity Plan", "create", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	if project_template:
		return _from_template(project, project_template)
	return _from_project(project)


def _from_template(project, template):
	start = getdate(frappe.db.get_value("Project", project, "expected_start_date") or nowdate())
	tasks = [frappe.get_doc("Task", row.task) for row in frappe.get_doc("Project Template", template).tasks]
	by_name = {t.name: t for t in tasks}

	def dates(t):
		begin = add_days(start, int(t.start or 0))
		return begin, add_days(begin, max(int(t.duration or 0), 0))

	phases, activities = [], []
	for t in tasks:
		if t.parent_task in by_name:
			continue
		begin, end = dates(t)
		phases.append({"phase_name": t.subject, "planned_start": begin, "planned_end": end, "weight": t.task_weight})
	for t in tasks:
		parent = by_name.get(t.parent_task)
		if not parent:
			continue
		begin, end = dates(t)
		dependency = next((by_name[d.task].subject for d in t.depends_on if d.task in by_name), None)
		activities.append(
			{
				"phase_name": parent.subject, "subject": t.subject, "start_date": begin, "end_date": end,
				"task_weight": t.task_weight, "depends_on_subject": dependency,
			}
		)
	_fit_phases(phases, activities)
	return {"phases": phases, "activities": activities}


def _from_project(project):
	phases, activities = [], []
	names = {}
	for p in frappe.get_all(
		"Task",
		filters={"project": project, "is_group": 1, "parent_task": ("is", "not set"), "status": ("!=", "Cancelled")},
		fields=["name", "subject", "exp_start_date", "exp_end_date", "task_weight", "description"],
		order_by="exp_start_date asc, lft asc",
	):
		names[p.name] = p.subject
		phases.append(
			{
				"phase": p.name, "phase_name": p.subject, "planned_start": _date(p.exp_start_date),
				"planned_end": _date(p.exp_end_date), "weight": p.task_weight, "description": strip_html(p.description or ""),
			}
		)
	if names:
		for t in frappe.get_all(
			"Task",
			filters={"project": project, "parent_task": ("in", list(names)), "status": ("!=", "Cancelled")},
			fields=["name", "subject", "parent_task", "exp_start_date", "exp_end_date", "task_weight"],
			order_by="exp_start_date asc, lft asc",
		):
			activities.append(
				{
					"task": t.name, "phase_name": names[t.parent_task], "subject": t.subject,
					"start_date": _date(t.exp_start_date), "end_date": _date(t.exp_end_date), "task_weight": t.task_weight,
				}
			)
	_fit_phases(phases, activities)
	return {"phases": phases, "activities": activities}


def _fit_phases(phases, activities):
	"""Give undated rows a date and stretch each phase over its activities."""
	today = getdate(nowdate())
	for a in activities:
		a["start_date"] = a.get("start_date") or today
		a["end_date"] = a.get("end_date") or a["start_date"]
	for p in phases:
		inside = [a for a in activities if a["phase_name"] == p["phase_name"]]
		starts = [getdate(p["planned_start"])] if p.get("planned_start") else []
		ends = [getdate(p["planned_end"])] if p.get("planned_end") else []
		p["planned_start"] = min(starts + [getdate(a["start_date"]) for a in inside] or [today])
		p["planned_end"] = max(ends + [getdate(a["end_date"]) for a in inside] or [p["planned_start"]])


def _date(value):
	return getdate(value) if value else None


@frappe.whitelist()
def make_revision(source_name: str):
	"""A new draft plan loaded with the live phases, activities and items, ready to be changed."""
	source = frappe.get_doc("Project Activity Plan", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or not source.is_current:
		frappe.throw(_("Only the current approved plan can be revised."))
	doc = frappe.new_doc("Project Activity Plan")
	doc.update({"project": source.project, "company": source.company, "revision_of": source.name})
	live = _from_project(source.project)
	billing = {
		t.name: t
		for t in frappe.get_all(
			"Task",
			filters={"name": ("in", [p["phase"] for p in live["phases"]] or [""])},
			fields=["name", "muhick_planned_valuation", "muhick_planned_claim_date", "muhick_is_billing_milestone"],
		)
	}
	for p in live["phases"]:
		b = billing.get(p["phase"], {})
		p.update(
			planned_valuation=b.get("muhick_planned_valuation"),
			planned_claim_date=b.get("muhick_planned_claim_date"),
			is_billing_milestone=b.get("muhick_is_billing_milestone"),
			previous_start=p["planned_start"],
			previous_end=p["planned_end"],
		)
		doc.append("phases", p)
	previous = {a.task: a.depends_on_subject for a in source.activities if a.task}
	for a in live["activities"]:
		a["depends_on_subject"] = previous.get(a["task"])
		doc.append("activities", a)
	for item in source.items:
		doc.append(
			"items",
			{f: item.get(f) for f in ("phase_name", "item_code", "item_name", "qty", "uom", "required_by", "remarks")},
		)
	return doc
