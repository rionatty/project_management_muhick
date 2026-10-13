# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Supplier invoices that did not match the purchase order and the goods received, and those
where the mismatch was overridden and by whom."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Supplier Invoice"), "fieldtype": "Link", "options": "Purchase Invoice", "width": 170},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 180},
		{"fieldname": "bill_no", "label": _("Supplier Invoice No."), "fieldtype": "Data", "width": 140},
		{"fieldname": "base_grand_total", "label": _("Invoice Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "outstanding_amount", "label": _("Outstanding"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "muhick_match_status", "label": _("Match Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "on_hold", "label": _("On Hold"), "fieldtype": "Check", "width": 80},
		{"fieldname": "muhick_match_remarks", "label": _("Exceptions"), "fieldtype": "Data", "width": 420},
		{"fieldname": "muhick_match_overridden_by", "label": _("Overridden By"), "fieldtype": "Link", "options": "User", "width": 170},
		{"fieldname": "owner", "label": _("Posted By"), "fieldtype": "Link", "options": "User", "width": 170},
	]
	conditions = {
		"docstatus": ("<", 2),
		"muhick_match_status": ("in", ("Exception", "Overridden") if not filters.status else (filters.status,)),
	}
	if filters.company:
		conditions["company"] = filters.company
	if filters.supplier:
		conditions["supplier"] = filters.supplier
	if filters.from_date and filters.to_date:
		conditions["posting_date"] = ("between", [filters.from_date, filters.to_date])
	rows = frappe.get_all(
		"Purchase Invoice",
		filters=conditions,
		fields=[c["fieldname"] for c in columns],
		order_by="posting_date desc",
		limit=2000,
	)
	return columns, rows
