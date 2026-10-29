# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The bid's cost estimate is laid out sheet by sheet, as the business's budget workbook: a table per
section on the opportunity in place of its one table. Each line moves to its section's table (a line
without a section goes by its cost code, else to Installation Materials), every line is given its amount
as quoted and its currency, and the one table and its summary are taken off."""

from collections import defaultdict

import frappe

from project_management_muhick.muhick_projects.estimate import ESTIMATE_TABLES
from project_management_muhick.utils import calc


def execute():
	tables = {section: field for field, section in ESTIMATE_TABLES.items()}
	sections = {
		code: calc.section_of_cost_code(code, budget_section)
		for code, budget_section in frappe.get_all("Cost Code", fields=["name", "budget_section"], as_list=True)
	}
	counts = defaultdict(int)
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parenttype": "Opportunity", "parentfield": "muhick_estimate"},
		fields=["name", "parent", "section", "cost_code"],
		order_by="parent asc, idx asc",
	):
		section = line.section if line.section in tables else sections.get(line.cost_code) or "Installation Materials"
		field = tables.get(section, "muhick_materials")
		counts[(line.parent, field)] += 1
		frappe.db.set_value(
			"Project Budget Line", line.name,
			{"parentfield": field, "section": section, "idx": counts[(line.parent, field)]},
			update_modified=False,
		)
	frappe.db.sql(
		"""update `tabProject Budget Line` set quoted_amount = qty * rate * if(ifnull(people, 0) = 0, 1, people)
		where ifnull(quoted_amount, 0) = 0"""
	)
	# a line in the company's currency names it, so its amounts show in it whatever the bid's currency
	for parenttype in ("Opportunity", "Project Budget"):
		frappe.db.sql(
			f"""update `tabProject Budget Line` line
			inner join `tab{parenttype}` doc on doc.name = line.parent
			inner join `tabCompany` company on company.name = doc.company
			set line.currency = company.default_currency, line.exchange_rate = 1
			where line.parenttype = %s and ifnull(line.currency, '') = ''""",
			(parenttype,),
		)
	for field in ("muhick_estimate", "muhick_estimate_summary", "muhick_estimate_summary_section", "muhick_estimate_tab"):
		if frappe.db.exists("Custom Field", f"Opportunity-{field}"):
			frappe.delete_doc("Custom Field", f"Opportunity-{field}", ignore_permissions=True, force=True)
