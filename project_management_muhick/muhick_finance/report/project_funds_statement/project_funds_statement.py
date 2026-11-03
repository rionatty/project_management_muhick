# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every movement of one project's money, in date order, with what it has available after each: what came into and went
out of the bank and cash accounts on the project, what was allocated to or from other projects, and what was refunded."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from project_management_muhick.muhick_finance import funds


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 105},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 150},
		{"fieldname": "document", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "document_type", "width": 170},
		{"fieldname": "account", "label": _("Bank or Cash Account"), "fieldtype": "Link", "options": "Account", "width": 200},
		{"fieldname": "details", "label": _("Details"), "fieldtype": "Data", "width": 300},
		{"fieldname": "money_in", "label": _("Money In"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "money_out", "label": _("Money Out"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "balance", "label": _("Funds Available"), "fieldtype": "Currency", "width": 150},
	]
	if not filters.project:
		return columns, []
	entries = _entries(filters.project, filters.to_date)
	entries.sort(key=lambda entry: getdate(entry["date"]))
	start = getdate(filters.from_date) if filters.from_date else None
	balance, rows, opening = 0.0, [], None
	for entry in entries:
		balance += flt(entry.get("money_in")) - flt(entry.get("money_out"))
		if start and getdate(entry["date"]) < start:
			opening = {"date": start, "details": _("Opening balance"), "balance": balance, "bold": 1}
			continue
		rows.append({**entry, "balance": balance})
	return columns, ([opening] if opening else []) + rows


def _entries(project, upto) -> list:
	company = frappe.db.get_value("Project", project, "company")
	entries = [
		{
			"date": row.posting_date,
			"document_type": row.voucher_type,
			"document": row.voucher_no,
			"account": row.account,
			"details": ": ".join(filter(None, (row.against, row.remarks))),
			"money_in": flt(row.debit),
			"money_out": flt(row.credit),
		}
		for row in funds.movements(company, upto)
		if row.project == project
	]
	for allocation in funds.allocations(company, upto):
		if project not in (allocation.from_project, allocation.to_project):
			continue
		lent = allocation.from_project == project
		other = allocation.to_project if lent else allocation.from_project
		movement = _("Allocated to {0}") if lent else _("Allocated from {0}")
		entries.append(
			{
				"date": allocation.transfer_date,
				"document_type": "Resource Allocation",
				"document": allocation.name,
				"account": allocation.from_bank_account,
				"details": ": ".join(filter(None, (movement.format(other), allocation.purpose))),
				"money_in": 0.0 if lent else flt(allocation.base_amount),
				"money_out": flt(allocation.base_amount) if lent else 0.0,
			}
		)
		for refund in allocation.refunds:
			movement = _("Refunded by {0}") if lent else _("Refunded to {0}")
			entries.append(
				{
					"date": refund.refund_date,
					"document_type": "Resource Allocation",
					"document": allocation.name,
					"account": refund.from_bank_account,
					"details": ": ".join(filter(None, (movement.format(other), refund.reference))),
					"money_in": flt(refund.base_amount) if lent else 0.0,
					"money_out": 0.0 if lent else flt(refund.base_amount),
				}
			)
	return entries
