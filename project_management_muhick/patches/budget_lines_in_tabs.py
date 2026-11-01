# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A budget's lines, until now one table, go to the table of their section, as on the opportunity."""

from collections import defaultdict

import frappe

from project_management_muhick.muhick_projects.estimate import ESTIMATE_TABLES
from project_management_muhick.utils import calc


def execute():
	tables = {section: field for field, section in ESTIMATE_TABLES.items()}
	numbers = defaultdict(int)
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parenttype": "Project Budget", "parentfield": "lines"},
		fields=["name", "parent", "section", "cost_code"],
		order_by="parent asc, idx asc",
	):
		section = line.section
		if section not in tables and line.cost_code:
			section = calc.section_of_cost_code(line.cost_code, frappe.get_cached_value("Cost Code", line.cost_code, "budget_section"))
		table = tables.get(section, "muhick_materials")
		numbers[(line.parent, table)] += 1
		frappe.db.set_value(
			"Project Budget Line",
			line.name,
			{"parentfield": table, "section": ESTIMATE_TABLES[table], "idx": numbers[(line.parent, table)]},
			update_modified=False,
		)
