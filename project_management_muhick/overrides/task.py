# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Milestones (phases) and their activities are standard Tasks: a milestone is a group task of the
project and its activities are child tasks. Every project task belongs to a milestone. The approved
activity plan stays in charge of names, dates and weights; activity progress rolls up to the
milestone and the milestones up to the project; the Project Manager is told when a billing
milestone is complete. The milestone's form shows its activities, items and budget."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import phase_done
from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import notify, project_manager_of

PLAN_FIELDS = (
	"subject", "parent_task", "is_group", "exp_start_date", "exp_end_date", "task_weight",
	"muhick_planned_valuation", "muhick_planned_claim_date", "muhick_is_billing_milestone",
)
DATES = ("exp_start_date", "exp_end_date", "muhick_planned_claim_date")
NUMBERS = ("task_weight", "muhick_planned_valuation", "is_group", "muhick_is_billing_milestone")


def validate(doc, method=None):
	require_milestone(doc)
	before = None if doc.is_new() else doc.get_doc_before_save()
	if not before or not doc.get("muhick_activity_plan"):
		return
	if not frappe.flags.muhick_applying_plan:
		changed = [doc.meta.get_label(f) for f in PLAN_FIELDS if _changed(before, doc, f)]
		if changed:
			frappe.throw(
				_("{0} of {1} come from the approved activity plan. Change them through a plan revision.").format(
					", ".join(changed), doc.subject
				)
			)
	if doc.get("muhick_billing_status") and flt(doc.progress) < flt(before.progress):
		frappe.throw(_("{0} has been claimed; its progress cannot be reduced.").format(doc.subject))


def require_milestone(doc):
	"""Every task of a project belongs to one of its milestones."""
	if not doc.project or doc.is_group or doc.get("is_template") or frappe.flags.muhick_applying_plan:
		return
	if doc.parent_task:
		if frappe.db.get_value("Task", doc.parent_task, "project") != doc.project:
			frappe.throw(_("Milestone {0} belongs to another project.").format(doc.parent_task))
		return
	# ERPNext's Project Template copy inserts the tasks first and links their milestone just after
	if doc.get("template_task"):
		return
	if frappe.db.exists("Task", {"project": doc.project, "is_group": 1, "status": ("!=", "Cancelled")}):
		frappe.throw(_("Choose the Milestone / Phase that task {0} belongs to.").format(doc.subject))


def _changed(before, doc, field):
	old, new = before.get(field), doc.get(field)
	if field in DATES:
		return (getdate(old) if old else None) != (getdate(new) if new else None)
	if field in NUMBERS:
		return abs(flt(old) - flt(new)) > 1e-9
	return cstr(old) != cstr(new)


def on_update(doc, method=None):
	if not doc.project or frappe.flags.muhick_applying_plan:
		return  # the plan rolls the project up once it has saved every task
	if doc.parent_task:
		roll_up(doc.parent_task)
	elif doc.is_group:
		before = doc.get_doc_before_save()
		_announce_completion(doc, before)
		project_api.update_progress(doc.project)


def roll_up(phase):
	"""A phase's progress is the weighted progress of its activities."""
	children = frappe.get_all(
		"Task",
		filters={"parent_task": phase, "status": ("!=", "Cancelled")},
		fields=["task_weight", "progress", "status"],
	)
	if not children:
		return
	task = frappe.get_doc("Task", phase)
	progress = calc.weighted_progress([(c.task_weight, c.progress) for c in children])
	values = {}
	if abs(progress - flt(task.progress)) > 0.005:
		values["progress"] = progress
	if all(c.status == "Completed" for c in children):
		values.update(status="Completed", progress=100)
	elif progress > 0 and task.status == "Open":
		values["status"] = "Working"
	if not values:
		return
	before = frappe._dict(progress=task.progress, status=task.status)
	frappe.db.set_value("Task", phase, values, update_modified=False)
	task.update(values)
	if not task.parent_task:
		_announce_completion(task, before)
		project_api.update_progress(task.project)


def _announce_completion(task, before):
	"""A billing phase that has just been completed is claimed."""
	if not task.get("muhick_is_billing_milestone") or task.get("muhick_billing_status"):
		return
	if phase_done(task) and not (before and phase_done(before)):
		notify(
			[project_manager_of(task.project)],
			_("Milestone {0} is complete. Raise the Service Delivery Note / Claim.").format(task.subject),
			doc=frappe._dict(doctype="Task", name=task.name),
		)


@frappe.whitelist()
def get_milestone_overview(task: str) -> dict:
	"""For the milestone's own form: its activities, the items the approved plan needs for it
	against what has been requested so far, and its budget."""
	doc = frappe.get_doc("Task", task)
	doc.check_permission("read")
	activities = frappe.get_all(
		"Task",
		filters={"parent_task": task, "status": ("!=", "Cancelled")},
		fields=["name", "subject", "status", "progress", "exp_start_date", "exp_end_date"],
		order_by="exp_start_date asc, lft asc",
	)
	items, budget = [], 0.0
	if doc.project:
		plan = frappe.db.get_value("Project Activity Plan", {"project": doc.project, "docstatus": 1, "is_current": 1}, "name")
		milestone = plan and frappe.db.get_value("Project Activity Plan Phase", {"parent": plan, "phase": task}, "phase_name")
		if milestone:
			requested = dict(
				frappe.db.sql(
					"""
					select mri.item_code, sum(mri.stock_qty)
					from `tabMaterial Request Item` mri inner join `tabMaterial Request` mr on mr.name = mri.parent
					where mr.docstatus < 2 and mr.muhick_phase = %s
					group by mri.item_code
					""",
					(task,),
				)
			)
			for row in frappe.get_all(
				"Project Activity Plan Item",
				filters={"parent": plan, "phase_name": milestone},
				fields=["item_code", "item_name", "qty", "uom", "required_by"],
				order_by="idx asc",
			):
				row.requested = flt(requested.get(row.item_code))
				items.append(row)
		approved = budget_engine.get_approved_budget(doc.project)
		if approved:
			budget = flt(
				frappe.db.sql(
					"select sum(amount) from `tabProject Budget Line` where parent = %s and phase = %s", (approved, task)
				)[0][0]
			)
	return {"activities": activities, "items": items, "budget": budget}
