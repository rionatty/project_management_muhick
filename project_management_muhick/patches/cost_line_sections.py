# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Cost estimate and budget lines are kept in the sections of the business's budget sheets (Equipment,
Installation Materials, Taxes and Freight, Labour, Tools and Equipment, Preliminaries, Administrative);
the lines already there take theirs from their cost code."""

import frappe

from project_management_muhick.utils import calc


def execute():
	for code, budget_section in frappe.get_all("Cost Code", fields=["name", "budget_section"], as_list=True):
		section = calc.section_of_cost_code(code, budget_section)
		if section:
			frappe.db.sql(
				"update `tabProject Budget Line` set section = %s where cost_code = %s and ifnull(section, '') = ''",
				(section, code),
			)
