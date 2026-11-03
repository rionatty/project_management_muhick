# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Allocations now name their bank accounts and hold their amounts in the From account's currency. One made before that was
in the company's currency, and which bank it came from is not known, so it counts in the projects' totals only."""

import frappe


def execute():
	for allocation in frappe.get_all("Resource Allocation", fields=["name", "company", "amount", "outstanding_amount"]):
		home = frappe.get_cached_value("Company", allocation.company, "default_currency")
		frappe.db.set_value(
			"Resource Allocation",
			allocation.name,
			{
				"company_currency": home,
				"currency": home,
				"to_currency": home,
				"exchange_rate": 1,
				"base_amount": allocation.amount,
				"received_amount": allocation.amount,
				"base_outstanding_amount": allocation.outstanding_amount,
			},
			update_modified=False,
		)
	for refund in frappe.get_all("Resource Allocation Refund", fields=["name", "amount"]):
		frappe.db.set_value(
			"Resource Allocation Refund",
			refund.name,
			{"exchange_rate": 1, "base_amount": refund.amount, "bank_amount": refund.amount, "received_amount": refund.amount},
			update_modified=False,
		)
