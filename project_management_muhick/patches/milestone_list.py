# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Milestones come from one shared list now, ERPNext's Task Type.

Adds the milestone names already used on activity plans and project milestone tasks to the list,
gives each project milestone task its list entry, moves a milestone already picked on a BOQ line
(then a project milestone task) to its list entry, and refreshes the BOQ quantities. A failing
step is logged, not raised, so the migration carries on."""

import frappe

from project_management_muhick.muhick_projects.doctype.project_boq.project_boq import update_quantities
from project_management_muhick.muhick_projects.utils import ensure_milestone


def execute():
	for step in (fill_list, move_boq_milestones, refresh_boq_quantities):
		frappe.db.savepoint("muhick_milestone_list")
		try:
			step()
		except Exception:
			frappe.db.rollback(save_point="muhick_milestone_list")
			frappe.log_error(title=f"Muhick: moving to the shared milestone list failed at {step.__name__}")


def fill_list():
	for name in set(frappe.get_all("Project Activity Plan Phase", pluck="phase_name")):
		ensure_milestone(name)
	for task in frappe.get_all(
		"Task",
		filters={"project": ("is", "set"), "is_group": 1, "parent_task": ("is", "not set"), "type": ("is", "not set")},
		fields=["name", "subject"],
	):
		frappe.db.set_value("Task", task.name, "type", ensure_milestone(task.subject), update_modified=False)


def move_boq_milestones():
	if not frappe.db.has_column("Project BOQ Item", "phase"):
		return
	for row in frappe.db.sql(
		"""select i.name, t.type from `tabProject BOQ Item` i inner join `tabTask` t on t.name = i.phase
		where ifnull(i.milestone, '') = '' and ifnull(t.type, '') != ''""",
		as_dict=True,
	):
		frappe.db.set_value("Project BOQ Item", row.name, "milestone", row.type, update_modified=False)


def refresh_boq_quantities():
	for project in frappe.get_all("Project", filters={"muhick_boq": ("is", "set")}, pluck="name"):
		update_quantities(project)
