# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Tax withheld from suppliers and subcontractors, entry by entry. Filter to one supplier and a
period and print it to support the withholding tax certificate given to that supplier."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "withholding_date", "label": _("Date Withheld"), "fieldtype": "Date", "width": 115},
		{"fieldname": "party", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 180},
		{"fieldname": "party_name", "label": _("Supplier Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "tax_id", "label": _("Tax ID"), "fieldtype": "Data", "width": 130},
		{"fieldname": "tax_withholding_category", "label": _("Category"), "fieldtype": "Link", "options": "Tax Withholding Category", "width": 170},
		{"fieldname": "taxable_doctype", "label": _("Document Type"), "fieldtype": "Data", "width": 140},
		{"fieldname": "taxable_name", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "taxable_doctype", "width": 170},
		{"fieldname": "taxable_date", "label": _("Document Date"), "fieldtype": "Date", "width": 115},
		{"fieldname": "taxable_amount", "label": _("Taxable Amount"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "tax_rate", "label": _("Rate %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "withholding_amount", "label": _("Tax Withheld"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
	]
	conditions = {"docstatus": 1, "party_type": "Supplier", "status": ("not in", ("Cancelled", "Duplicate"))}
	if filters.company:
		conditions["company"] = filters.company
	if filters.supplier:
		conditions["party"] = filters.supplier
	if filters.from_date and filters.to_date:
		conditions["withholding_date"] = ("between", [filters.from_date, filters.to_date])
	rows = frappe.get_all(
		"Tax Withholding Entry",
		filters=conditions,
		fields=[c["fieldname"] for c in columns if c["fieldname"] != "party_name"],
		order_by="withholding_date asc",
		limit=5000,
	)
	names = dict(
		frappe.get_all("Supplier", filters={"name": ("in", list({r.party for r in rows}))}, fields=["name", "supplier_name"], as_list=True)
	) if rows else {}
	for r in rows:
		r.party_name = names.get(r.party)
	return columns, rows
