# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Activity plan: milestones (phases) and tasks, approved COO -> Finance -> General Manager.

Approval creates the milestones and tasks. A later change to dates, weights or valuations is a
revision: a new plan that states why the schedule moved and goes through approval again, while
the first approved dates stay on each milestone as the baseline.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

MILESTONE_FIELDS = (
	"milestone_name", "description", "planned_start", "planned_end", "weight",
	"planned_valuation", "planned_claim_date", "is_billing_milestone",
)


class ProjectActivityPlan(Document):
	def validate(self):
		self.check_single_open_plan()
		self.validate_milestones()
		self.validate_tasks()
		self.set_summary()
		if self.revision_of:
			if not (self.revision_reason or "").strip() or not self.change_driver:
				frappe.throw(_("A revision must state what drove the change and the reason."))
			self.check_dropped_milestones()

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

	def validate_milestones(self):
		names = set()
		for row in self.milestones:
			row.milestone_name = (row.milestone_name or "").strip()
			if row.milestone_name in names:
				frappe.throw(_("Milestones row {0}: {1} appears twice.").format(row.idx, row.milestone_name))
			names.add(row.milestone_name)
			if getdate(row.planned_end) < getdate(row.planned_start):
				frappe.throw(_("Milestones row {0}: Planned End is before Planned Start.").format(row.idx))
		self.total_weight = sum(flt(r.weight) for r in self.milestones)
		if self.total_weight and abs(self.total_weight - 100) > 0.01:
			frappe.throw(_("Milestone weights must total 100% (they total {0}%).").format(f"{self.total_weight:g}"))

	def validate_tasks(self):
		milestones = {r.milestone_name for r in self.milestones}
		subjects = set()
		for row in self.tasks:
			row.subject = (row.subject or "").strip()
			row.milestone_name = (row.milestone_name or "").strip()
			if row.subject in subjects:
				frappe.throw(_("Tasks row {0}: {1} appears twice.").format(row.idx, row.subject))
			subjects.add(row.subject)
			if row.milestone_name not in milestones:
				frappe.throw(_("Tasks row {0}: {1} is not a milestone of this plan.").format(row.idx, row.milestone_name))
			if getdate(row.end_date) < getdate(row.start_date):
				frappe.throw(_("Tasks row {0}: End is before Start.").format(row.idx))
		for row in self.tasks:
			dependency = (row.depends_on_subject or "").strip()
			if dependency and (dependency == row.subject or dependency not in subjects):
				frappe.throw(_("Tasks row {0}: {1} is not another task of this plan.").format(row.idx, dependency))

	def set_summary(self):
		self.plan_start = min(getdate(r.planned_start) for r in self.milestones)
		self.plan_end = max(getdate(r.planned_end) for r in self.milestones)
		self.total_planned_valuation = sum(flt(r.planned_valuation) for r in self.milestones)
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

	def check_dropped_milestones(self):
		"""A milestone left out of a revision is removed, which is only allowed while it is untouched."""
		kept = {r.milestone for r in self.milestones if r.milestone}
		for m in frappe.get_all(
			"Project Milestone", filters={"project": self.project}, fields=["name", "milestone_name", "percent_complete", "status"]
		):
			if m.name not in kept and (flt(m.percent_complete) or m.status in ("Claimed", "Certified")):
				frappe.throw(_("{0} has progress recorded and cannot be removed from the plan.").format(m.milestone_name))

	# ------------------------------------------------------------------ approval
	def on_submit(self):
		self.extend_project_dates()
		milestone_names = self.apply_milestones()
		self.apply_tasks(milestone_names)
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
		dates += [getdate(t.start_date) for t in self.tasks] + [getdate(t.end_date) for t in self.tasks]
		values = {}
		if not start or getdate(start) > min(dates):
			values["expected_start_date"] = min(dates)
		if not end or getdate(end) < max(dates):
			values["expected_end_date"] = max(dates)
		if values:
			frappe.db.set_value("Project", self.project, values)

	def apply_milestones(self) -> dict:
		names = {}
		for sequence, row in enumerate(self.milestones, start=1):
			milestone = frappe.get_doc("Project Milestone", row.milestone) if row.milestone else frappe.new_doc("Project Milestone")
			milestone.flags.from_activity_plan = True
			milestone.project = self.project
			milestone.sequence = sequence
			milestone.activity_plan = self.name
			for field in MILESTONE_FIELDS:
				milestone.set(field, row.get(field))
			if not milestone.baseline_start:
				milestone.baseline_start = row.planned_start
				milestone.baseline_end = row.planned_end
			milestone.flags.ignore_permissions = True
			milestone.save()
			if row.milestone != milestone.name:
				row.db_set("milestone", milestone.name, update_modified=False)
			names[row.milestone_name] = milestone.name
		if self.revision_of:
			dropped = frappe.get_all(
				"Project Milestone", filters={"project": self.project, "name": ("not in", list(names.values()))}, pluck="name"
			)
			self.delete_milestones(dropped)
		return names

	def delete_milestones(self, milestones):
		"""Remove milestones that are no longer in the plan. Their tasks stay, without a milestone."""
		if not milestones:
			return
		frappe.db.set_value("Task", {"muhick_milestone": ("in", milestones)}, "muhick_milestone", None)
		for name in milestones:
			frappe.delete_doc("Project Milestone", name, ignore_permissions=True)

	def apply_tasks(self, milestone_names):
		tasks = {}
		for row in self.tasks:
			task = frappe.get_doc("Task", row.task) if row.task else frappe.new_doc("Task")
			task.subject = row.subject
			task.project = self.project
			task.exp_start_date = row.start_date
			task.exp_end_date = row.end_date
			task.task_weight = flt(row.task_weight)
			task.muhick_milestone = milestone_names[row.milestone_name]
			if row.description:
				task.description = row.description
			task.flags.ignore_permissions = True
			task.save()
			if row.task != task.name:
				row.db_set("task", task.name, update_modified=False)
			tasks[row.subject] = task
		for row in self.tasks:
			dependency = (row.depends_on_subject or "").strip()
			if not dependency:
				continue
			task, needed = tasks[row.subject], tasks[dependency].name
			if needed not in [d.task for d in task.get("depends_on") or []]:
				task.append("depends_on", {"task": needed})
				task.save()

	def on_cancel(self):
		if self.revision_of:
			frappe.throw(_("An approved revision cannot be cancelled. Raise a new revision to change the plan again."))
		started = frappe.db.exists("Project Milestone", {"project": self.project, "percent_complete": (">", 0)})
		if started:
			frappe.throw(_("Progress has been recorded against this plan. Revise the plan instead of cancelling it."))
		self.delete_milestones(frappe.get_all("Project Milestone", filters={"activity_plan": self.name}, pluck="name"))
		self.db_set("is_current", 0)
		if frappe.db.get_value("Project", self.project, "muhick_activity_plan") == self.name:
			frappe.db.set_value("Project", self.project, "muhick_activity_plan", None)


@frappe.whitelist()
def make_revision(source_name: str):
	"""A new draft plan loaded with the live milestones and tasks, ready to be changed."""
	source = frappe.get_doc("Project Activity Plan", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or not source.is_current:
		frappe.throw(_("Only the current approved plan can be revised."))
	doc = frappe.new_doc("Project Activity Plan")
	doc.update({"project": source.project, "company": source.company, "revision_of": source.name})
	for m in frappe.get_all(
		"Project Milestone",
		filters={"project": source.project},
		fields=["name", *MILESTONE_FIELDS],
		order_by="sequence asc",
	):
		row = {f: m.get(f) for f in MILESTONE_FIELDS}
		row.update(milestone=m.name, previous_start=m.planned_start, previous_end=m.planned_end)
		doc.append("milestones", row)
	milestone_names = {m.milestone: m.milestone_name for m in doc.milestones}
	previous = {t.task: t for t in source.tasks if t.task}
	for t in frappe.get_all(
		"Task",
		filters={"project": source.project, "muhick_milestone": ("in", list(milestone_names)), "status": ("!=", "Cancelled")},
		fields=["name", "subject", "exp_start_date", "exp_end_date", "task_weight", "muhick_milestone"],
		order_by="exp_start_date asc",
	):
		doc.append(
			"tasks",
			{
				"task": t.name,
				"subject": t.subject,
				"milestone_name": milestone_names[t.muhick_milestone],
				"start_date": getdate(t.exp_start_date) if t.exp_start_date else None,
				"end_date": getdate(t.exp_end_date) if t.exp_end_date else None,
				"task_weight": t.task_weight,
				"depends_on_subject": previous[t.name].depends_on_subject if t.name in previous else None,
			},
		)
	return doc
