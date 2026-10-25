# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bid security requests hold their securities and expenses as lines. Bid Security Charges becomes an
expense of the bid security (requested with it, not on the sales requisition), and a request already
entered gets one security line for its amount and one expense line for its funds."""

import frappe
from frappe.utils import flt

from project_management_muhick.setup.defaults import setup_crm_lists


def execute():
	setup_crm_lists()
	if frappe.db.get_value("Financial Requirement Type", "Bid Security Charges", "kind") == "Cost":
		frappe.db.set_value("Financial Requirement Type", "Bid Security Charges", "kind", "Bid Security Expense")
	for r in frappe.get_all("Bid Security Request", fields=["name", "amount", "funds_required"]):
		lines = (
			("Bid Security Line", "securities", {"security_type": "Bid Security", "amount": flt(r.amount)}, r.amount),
			("Bid Security Expense", "expenses", {"expense_type": "Bid Security Charges", "amount": flt(r.funds_required)}, r.funds_required),
		)
		for child, table, row, amount in lines:
			if flt(amount) and not frappe.db.exists(child, {"parent": r.name}):
				frappe.get_doc(
					{"doctype": child, "parent": r.name, "parenttype": "Bid Security Request", "parentfield": table, "idx": 1, **row}
				).db_insert()
