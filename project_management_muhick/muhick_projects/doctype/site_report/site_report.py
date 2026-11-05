# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Weekly, monthly, progress and completion reports. The system fills in what it already knows
(each milestone with its tasks against plan, casual labour by trade, materials issued, equipment on site);
the Project Manager adds the narrative, the reasons for being ahead or behind, and photos.

Progress is reported on each task, as the schedule has them. A milestone or group task reads what the tasks under it add
up to, weighted as they are for the project's progress. Submitting the report moves the tasks whose progress it changed,
and what they sit under follows; cancelling it moves back those that have not moved since."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import validate_dates
from project_management_muhick.overrides import project as project_api
from project_management_muhick.overrides import task as task_api
from project_management_muhick.utils import calc

PROGRESS_TABLE = "project_management_muhick/templates/print_formats/site_report_progress.html"
# a task the approved schedule does not know follows those it does, at its own level
NOT_ON_SCHEDULE = float("inf")
SAME = 0.005


class SiteReport(Document):
	def validate(self):
		validate_dates(self.period_from, self.period_to, _("Period From"), _("Period To"))
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		self.read_tasks()
		self.add_up()

	def read_tasks(self):
		"""Each row as its task stands now and as planned for the end of the period. A row whose progress has not been
		changed here follows its task, so a draft left lying cannot put a task back."""
		names = [row.phase for row in self.phases]
		if not names:
			return
		tasks = {
			task.name: task
			for task in frappe.get_all(
				"Task",
				filters={"name": ("in", names)},
				fields=["name", "project", "subject", "parent_task", "task_weight", "progress", "exp_start_date", "exp_end_date"],
			)
		}
		with_tasks_under = set(frappe.get_all("Task", filters={"parent_task": ("in", names), "status": ("!=", "Cancelled")}, pluck="parent_task"))
		for row in self.phases:
			task = tasks.get(row.phase)
			if not task or task.project != self.project:
				frappe.throw(_("{0} is not a task of project {1}. Use Fetch from System to load its tasks again.").format(row.subject or row.phase, self.project))
			if not _changed(row):
				row.actual_percent = flt(task.progress)
			if not 0 <= flt(row.actual_percent) <= 100:
				frappe.throw(_("{0}: progress must be between 0 and 100.").format(task.subject))
			row.update(
				{
					"subject": task.subject,
					"parent_task": task.parent_task,
					"task_weight": task.task_weight,
					"planned_start": task.exp_start_date,
					"planned_end": task.exp_end_date,
					"is_group": 1 if row.phase in with_tasks_under else 0,
					"previous_percent": flt(task.progress),
					"planned_percent": calc.planned_percent(task.exp_start_date, task.exp_end_date, self.period_to),
				}
			)

	def add_up(self):
		"""The rows come with what a row sits under before it, so the last are settled first."""
		under = defaultdict(list)
		for row in self.phases:
			under[row.parent_task or ""].append(row)
		for row in reversed(self.phases):
			tasks = under.get(row.phase)
			if tasks:
				row.planned_percent = calc.weighted_progress([(task.task_weight, task.planned_percent) for task in tasks])
				row.actual_percent = calc.weighted_progress([(task.task_weight, task.actual_percent) for task in tasks])
			row.variance_percent = flt(flt(row.actual_percent) - flt(row.planned_percent), 2)
		top = under[""]
		self.planned_progress = calc.weighted_progress([(row.task_weight, row.planned_percent) for row in top])
		self.overall_progress = calc.weighted_progress([(row.task_weight, row.actual_percent) for row in top])

	def reported(self) -> list:
		"""The rows this report changes the progress of. Those with tasks under them follow from those tasks."""
		return [row for row in self.phases if not row.is_group and _changed(row)]

	def before_submit(self):
		"""What a task's own form would refuse: it cannot be finished before those it follows, and what has been claimed
		cannot go back. All of it is said at once, and finishing them together in one report is fine."""
		rows = {row.phase: row for row in self.phases}
		problems = []
		finishing = {row.phase: row for row in self.reported() if flt(row.actual_percent) >= 100}
		needs = frappe.get_all("Task Depends On", filters={"parent": ("in", list(finishing))}, fields=["parent", "task"]) if finishing else []
		others = {need.task for need in needs if need.task not in rows}
		closed = set(frappe.get_all("Task", filters={"name": ("in", list(others)), "status": ("in", ("Completed", "Cancelled"))}, pluck="name")) if others else set()
		for need in needs:
			row = rows.get(need.task)
			if not (flt(row.actual_percent) >= 100 if row else need.task in closed):
				follows = row.subject if row else frappe.db.get_value("Task", need.task, "subject")
				problems.append(_("{0} cannot be finished before {1}, which it follows.").format(finishing[need.parent].subject, follows))
		for task in self.claimed(rows):
			if flt(rows[task.name].actual_percent) < flt(task.progress) - SAME:
				problems.append(_("{0} has been claimed; its progress cannot be reduced.").format(task.subject))
		if problems:
			frappe.throw("<br>".join(dict.fromkeys(problems)))

	def on_submit(self):
		self.move_tasks({row.phase: flt(row.actual_percent) for row in self.reported()})

	def before_cancel(self):
		if not self.reported():
			return
		rows = {row.phase: row for row in self.phases}
		for task in self.claimed(rows):
			if flt(rows[task.name].previous_percent) < flt(rows[task.name].actual_percent) - SAME:
				frappe.throw(_("{0} has been claimed since this report; it cannot be cancelled.").format(task.subject))

	def on_cancel(self):
		rows = self.reported()
		now = dict(frappe.get_all("Task", filters={"name": ("in", [row.phase for row in rows])}, fields=["name", "progress"], as_list=True)) if rows else {}
		self.move_tasks(
			{row.phase: flt(row.previous_percent) for row in rows if abs(flt(now.get(row.phase)) - flt(row.actual_percent)) <= SAME},
			_("Back to {0}%: Site Report {1} was cancelled."),
		)

	def claimed(self, rows) -> list:
		if not rows:
			return []
		return frappe.get_all("Task", filters={"name": ("in", list(rows)), "muhick_billing_status": ("is", "set")}, fields=["name", "subject", "progress"])

	def move_tasks(self, progress: dict, note: str | None = None):
		"""Each task's own timeline says which report moved it."""
		for name, percent in progress.items():
			task_api.set_progress(name, percent, self.period_to)
			frappe.get_doc("Task", name).add_comment("Info", (note or _("{0}% reported on Site Report {1}.")).format(f"{percent:g}", self.name))
		if progress:
			frappe.get_doc("Project", self.project).update_project()
			project_api.update_progress(self.project)

	def before_print(self, settings=None):
		self.print_templates = {"phases": PROGRESS_TABLE}

	@frappe.whitelist()
	def fetch_from_system(self):
		"""Fill the tables and summaries from the project's records for the period."""
		if self.docstatus != 0:
			frappe.throw(_("Only a draft report can be refreshed."))
		if not (self.project and self.period_from and self.period_to):
			frappe.throw(_("Select the project and the period first."))
		self.fetch_tasks()
		self.fetch_manpower()
		self.materials_used = self.get_materials_used()
		self.equipment_on_site = self.get_equipment_on_site()
		self.subcontractor_progress = self.get_subcontractor_progress()

	def fetch_tasks(self):
		"""Each milestone with every task under it, in the schedule's order. What has been typed on a task stays."""
		before = {row.phase: row for row in self.phases}
		self.set("phases", [])
		for task, level, row_id in schedule_tasks(self.project):
			row = before.get(task.name)
			self.append(
				"phases",
				{
					"phase": task.name,
					"level": level,
					"row_id": row_id,
					"previous_percent": row.previous_percent if row else task.progress,
					"actual_percent": row.actual_percent if row else task.progress,
					"remarks": row.remarks if row else None,
				},
			)
		self.read_tasks()
		self.add_up()

	def fetch_manpower(self):
		rows = frappe.db.sql(
			"""
			select l.trade, count(distinct lower(trim(l.worker_name))) as headcount, sum(l.days_worked) as man_days
			from `tabCasual Sheet Line` l inner join `tabCasual Sheet` s on s.name = l.parent
			where s.project = %(project)s and s.docstatus < 2
				and s.period_from <= %(to)s and s.period_to >= %(from)s
			group by l.trade order by l.trade
			""",
			{"project": self.project, "from": self.period_from, "to": self.period_to},
			as_dict=True,
		)
		self.set("manpower", [])
		for r in rows:
			self.append("manpower", {"trade": r.trade, "headcount": r.headcount, "man_days": r.man_days})

	def get_materials_used(self) -> str:
		rows = frappe.db.sql(
			"""
			select d.item_code, d.stock_uom, sum(d.transfer_qty) as qty
			from `tabStock Entry Detail` d inner join `tabStock Entry` se on se.name = d.parent
			where se.docstatus = 1 and se.purpose = 'Material Issue'
				and ifnull(nullif(d.project, ''), se.project) = %(project)s
				and se.posting_date between %(from)s and %(to)s
			group by d.item_code, d.stock_uom order by sum(d.amount) desc limit 25
			""",
			{"project": self.project, "from": self.period_from, "to": self.period_to},
			as_dict=True,
		)
		return "\n".join(f"{r.item_code}: {flt(r.qty):g} {r.stock_uom or ''}".strip() for r in rows)

	def get_equipment_on_site(self) -> str:
		rows = frappe.get_all(
			"Project Equipment Allocation",
			filters={"project": self.project, "status": ("in", ("Allocated", "Under Repair"))},
			fields=["equipment_name", "quantity", "status", "condition_out"],
			order_by="equipment_name asc",
		)
		return "\n".join(f"{r.equipment_name} x{r.quantity} ({_(r.status)}, {_(r.condition_out)})" for r in rows)

	def get_subcontractor_progress(self) -> str:
		rows = frappe.get_all(
			"Subcontract Agreement",
			filters={"project": self.project, "docstatus": 1, "status": ("in", ("Active", "Completed"))},
			fields=["supplier_name", "title", "contract_amount", "certified_to_date", "status"],
		)
		lines = []
		for r in rows:
			percent = flt(r.certified_to_date) / flt(r.contract_amount) * 100 if flt(r.contract_amount) else 0
			lines.append(f"{r.supplier_name}, {r.title}: {percent:.0f}% certified ({_(r.status)})")
		return "\n".join(lines)


def _changed(row) -> bool:
	return abs(flt(row.actual_percent) - flt(row.previous_percent)) > SAME


def schedule_tasks(project) -> list:
	"""(task, how deep it sits, its ID on the schedule) for each task of the project that is not cancelled, what it sits
	under coming first and the rows in the approved schedule's order."""
	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "status": ("!=", "Cancelled"), "is_template": 0},
		fields=["name", "parent_task", "progress"],
		order_by="exp_start_date asc, lft asc",
	)
	plan = frappe.db.get_value("Project", project, "muhick_activity_plan")
	ids = (
		dict(frappe.get_all("Project Activity Plan Activity", filters={"parent": plan, "task": ("is", "set")}, fields=["task", "row_id"], as_list=True))
		if plan
		else {}
	)
	under = defaultdict(list)
	for task in sorted(tasks, key=lambda task: ids.get(task.name, NOT_ON_SCHEDULE)):
		under[task.parent_task or ""].append(task)
	rows = []

	def walk(parent, level):
		for task in under[parent]:
			rows.append((task, level, ids.get(task.name)))
			walk(task.name, level + 1)

	walk("", 0)
	return rows
