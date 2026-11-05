# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""What each person holds of the company's money: what was paid to their account, less what they have accounted for and
returned, with what they were refunded added back. It reads the postings on the staff advance account, so it adds up to that
account's balance, and lists the requisitions still open against them."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate

from project_management_muhick.muhick_finance.cash_requisition import staff_account

OPEN = ("Paid", "Accountability Submitted", "Accounted")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 140},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "given", "label": _("Paid to Their Account"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "cleared", "label": _("Accounted For or Returned"), "fieldtype": "Currency", "width": 180},
		{"fieldname": "held", "label": _("Held Now"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "account_by", "label": _("Earliest Account By"), "fieldtype": "Date", "width": 140},
		{"fieldname": "days_overdue", "label": _("Days Overdue"), "fieldtype": "Int", "width": 110},
		{"fieldname": "requisitions", "label": _("Open Requisitions"), "fieldtype": "Data", "width": 300},
	]
	if not filters.company:
		return columns, []
	rows = frappe.db.sql(
		"""
		select party as employee, sum(debit) as given, sum(credit) as cleared, sum(debit - credit) as held
		from `tabGL Entry`
		where account = %(account)s and party_type = 'Employee' and is_cancelled = 0
		group by party
		""",
		{"account": staff_account(filters.company)},
		as_dict=True,
	)
	if not filters.show_cleared:
		rows = [row for row in rows if abs(flt(row.held)) > 0.005]
	names = {
		e.name: e.employee_name
		for e in frappe.get_all("Employee", filters={"name": ("in", [row.employee for row in rows])}, fields=["name", "employee_name"])
	} if rows else {}
	open_ones = defaultdict(list)
	for doctype in ("Project Requisition", "Sales Requisition"):
		for doc in frappe.get_all(
			doctype,
			filters={"company": filters.company, "docstatus": 1, "status": ("in", OPEN), "employee": ("is", "set")},
			fields=["name", "employee", "accountability_due_date"],
		):
			open_ones[doc.employee].append(doc)
	today = nowdate()
	for row in rows:
		row.employee_name = names.get(row.employee)
		docs = open_ones[row.employee]
		row.requisitions = ", ".join(sorted(doc.name for doc in docs))
		due = [doc.accountability_due_date for doc in docs if doc.accountability_due_date]
		row.account_by = min(due, default=None)
		row.days_overdue = max(date_diff(today, row.account_by), 0) if row.account_by else 0
	rows.sort(key=lambda row: -flt(row.held))
	return columns, rows
