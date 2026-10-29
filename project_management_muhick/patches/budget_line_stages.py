# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Budget lines carry their stage from the shared milestone list, as the bid's cost estimate does: the
lines already placed in a project milestone take its stage. The tools cost code covers tools bought as
well as hired, unless Muhick has already renamed it."""

import frappe

OLD_TOOLS_NAME = "Equipment and Tools Hire"
TOOLS_NAME = "Equipment and Tools (Hire or Purchase)"


def execute():
	frappe.db.sql(
		"""
		update `tabProject Budget Line` line
		inner join `tabTask` task on task.name = line.phase
		set line.stage = task.type
		where line.parenttype = 'Project Budget' and ifnull(line.stage, '') = '' and ifnull(task.type, '') != ''
		"""
	)
	if frappe.db.get_value("Cost Code", "WRK-300", "cost_code_name") == OLD_TOOLS_NAME:
		frappe.db.set_value("Cost Code", "WRK-300", "cost_code_name", TOOLS_NAME)
