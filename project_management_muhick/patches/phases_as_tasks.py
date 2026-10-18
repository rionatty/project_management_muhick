# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Phases are standard Tasks now (a phase is a group task, its activities child tasks).

Moves what an earlier version kept in Project Milestone, and in the plan and site report rows
that pointed to it, onto phase tasks, re-points every link, and removes the old custom fields.
Each step is skipped when there is nothing to move; a failing step is logged, not raised, so the
migration carries on."""

import frappe
from frappe.utils.nestedset import rebuild_tree

STATUS = {"Not Started": "Open", "In Progress": "Working", "Completed": "Completed", "Claimed": "Completed", "Certified": "Completed"}

# doctype, old column, new column: a link to a milestone becomes a link to its phase task
LINKS = (
	("Material Request", "muhick_milestone", "muhick_phase"),
	("Stock Entry", "muhick_milestone", "muhick_phase"),
	("Project Budget Line", "milestone", "phase"),
	("Casual Sheet", "milestone", "phase"),
	("Labour Schedule", "milestone", "phase"),
	("Project Requisition", "milestone", "phase"),
	("Subcontract RFQ", "milestone", "phase"),
	("Project Claim", "milestone", "phase"),
	("Subcontract Agreement Milestone", "project_milestone", "phase"),
	("Service Receipt Note Item", "project_milestone", "phase"),
)

# old child table, new child table, table field on the parent, renamed columns, column holding a milestone
CHILD_TABLES = (
	("Project Activity Plan Milestone", "Project Activity Plan Phase", "phases", {"milestone_name": "phase_name", "milestone": "phase"}, "milestone"),
	("Project Activity Plan Task", "Project Activity Plan Activity", "activities", {"milestone_name": "phase_name"}, None),
	("Site Report Milestone", "Site Report Phase", "phases", {"milestone": "phase"}, "milestone"),
)

OLD_FIELDS = ("Material Request-muhick_milestone", "Stock Entry-muhick_milestone", "Task-muhick_milestone")


def execute():
	from project_management_muhick.setup.custom_fields import setup_custom_fields

	# the new phase fields are normally added after patches run; they must exist before data moves in
	setup_custom_fields()
	frappe.flags.muhick_applying_plan = True
	try:
		phases = _step(milestones_to_tasks) or {}
		_step(repoint_links, phases)
		_step(copy_child_rows, phases)
		_step(drop_old_fields)
	finally:
		frappe.flags.muhick_applying_plan = False


def _step(fn, *args):
	frappe.db.savepoint("muhick_phases")
	try:
		return fn(*args)
	except Exception:
		frappe.db.rollback(save_point="muhick_phases")
		frappe.log_error(title=f"Muhick: moving milestones to phase tasks failed at {fn.__name__}")


def milestones_to_tasks() -> dict:
	"""One group task per old milestone. Returns {milestone name: task name}."""
	if not frappe.db.table_exists("Project Milestone"):
		return {}
	phases = {}
	for m in frappe.db.sql("select * from `tabProject Milestone` order by project, sequence", as_dict=True):
		existing = frappe.db.get_value("Task", {"project": m.project, "subject": m.milestone_name, "is_group": 1}, "name")
		if existing:
			phases[m.name] = existing
			continue
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": m.milestone_name,
				"project": m.project,
				"is_group": 1,
				"status": STATUS.get(m.status, "Open"),
				"progress": m.percent_complete,
				"exp_start_date": m.planned_start,
				"exp_end_date": m.planned_end,
				"task_weight": m.weight,
				"act_start_date": m.actual_start,
				"act_end_date": m.actual_end,
				"description": m.description,
				"muhick_activity_plan": m.activity_plan,
				"muhick_baseline_start": m.baseline_start,
				"muhick_baseline_end": m.baseline_end,
				"muhick_is_billing_milestone": m.is_billing_milestone,
				"muhick_planned_valuation": m.planned_valuation,
				"muhick_planned_claim_date": m.planned_claim_date,
				"muhick_billing_status": m.status if m.status in ("Claimed", "Certified") else None,
			}
		)
		task.flags.update(ignore_validate=True, ignore_links=True, ignore_permissions=True, from_project=True)
		task.insert()
		phases[m.name] = task.name
	return phases


def repoint_links(phases):
	if not phases:
		return
	# activities hung under a milestone become child tasks of its phase
	if frappe.db.has_column("Task", "muhick_milestone"):
		for task, milestone in frappe.db.sql("select name, muhick_milestone from `tabTask` where ifnull(muhick_milestone, '') != ''"):
			if milestone in phases and task != phases[milestone]:
				frappe.db.set_value("Task", task, "parent_task", phases[milestone], update_modified=False)
		rebuild_tree("Task")
	for doctype, old, new in LINKS:
		if not (frappe.db.has_column(doctype, old) and frappe.db.has_column(doctype, new)):
			continue
		for milestone, task in phases.items():
			frappe.db.sql(
				f"update `tab{doctype}` set `{new}` = %s where `{old}` = %s and ifnull(`{new}`, '') = ''", (task, milestone)
			)


def copy_child_rows(phases):
	for old, new, parentfield, renamed, link in CHILD_TABLES:
		if not (frappe.db.table_exists(old) and frappe.db.table_exists(new)):
			continue
		columns = set(frappe.db.get_table_columns(new))
		copied = set(frappe.db.sql_list(f"select name from `tab{new}`"))
		for row in frappe.db.sql(f"select * from `tab{old}`", as_dict=True):
			if row.name in copied:
				continue
			values = {renamed.get(k, k): v for k, v in row.items()}
			if link:
				values[renamed[link]] = phases.get(row.get(link))
			values["parentfield"] = parentfield
			values = {k: v for k, v in values.items() if k in columns}
			frappe.db.sql(
				"insert into `tab{0}` ({1}) values ({2})".format(
					new, ", ".join(f"`{k}`" for k in values), ", ".join(["%s"] * len(values))
				),
				tuple(values.values()),
			)


def drop_old_fields():
	for name in OLD_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
