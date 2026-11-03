# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""How resources flow between projects: every approved allocation, from which project to which, what has been refunded and
what is still to refund, and which are past their expected refund date. The chart sums it up project by project."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate

from project_management_muhick.muhick_finance import funds


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "allocation", "label": _("Resource Allocation"), "fieldtype": "Link", "options": "Resource Allocation", "width": 160},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 105},
		{"fieldname": "from_project", "label": _("Funds From Project"), "fieldtype": "Link", "options": "Project", "width": 170},
		{"fieldname": "to_project", "label": _("Funds To Project"), "fieldtype": "Link", "options": "Project", "width": 170},
		{"fieldname": "purpose", "label": _("Purpose"), "fieldtype": "Data", "width": 240},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "refunded", "label": _("Refunded"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "outstanding", "label": _("Still to Refund"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "expected_refund_date", "label": _("Expected Refund Date"), "fieldtype": "Date", "width": 150},
		{"fieldname": "days_overdue", "label": _("Days Overdue"), "fieldtype": "Int", "width": 110},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
	]
	today = nowdate()
	rows, out, into = [], defaultdict(float), defaultdict(float)
	for allocation in funds.allocations(filters.company):
		if filters.project and filters.project not in (allocation.from_project, allocation.to_project):
			continue
		still = flt(allocation.outstanding)
		if filters.only_open and still <= 0.005:
			continue
		out[allocation.from_project] += still
		into[allocation.to_project] += still
		due = allocation.expected_refund_date
		rows.append(
			{
				"allocation": allocation.name,
				"date": allocation.transfer_date,
				"from_project": allocation.from_project,
				"to_project": allocation.to_project,
				"purpose": allocation.purpose,
				"amount": flt(allocation.amount),
				"refunded": allocation.refunded,
				"outstanding": still,
				"expected_refund_date": due,
				"days_overdue": max(date_diff(today, due), 0) if due and still > 0.005 else 0,
				"status": allocation.status,
			}
		)
	rows.sort(key=lambda row: (-row["days_overdue"], str(row["date"])))
	projects = sorted({*out, *into})
	chart = {
		"data": {
			"labels": projects,
			"datasets": [
				{"name": _("Allocated to Other Projects"), "values": [out[project] for project in projects]},
				{"name": _("Allocated from Other Projects"), "values": [into[project] for project in projects]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
	summary = [
		{"value": sum(row["amount"] for row in rows), "label": _("Allocated"), "datatype": "Currency", "indicator": "Blue"},
		{"value": sum(row["refunded"] for row in rows), "label": _("Refunded"), "datatype": "Currency", "indicator": "Green"},
		{"value": sum(row["outstanding"] for row in rows), "label": _("Still to Refund"), "datatype": "Currency", "indicator": "Orange"},
		{"value": sum(row["outstanding"] for row in rows if row["days_overdue"]), "label": _("Overdue"), "datatype": "Currency", "indicator": "Red"},
	]
	return columns, rows, None, chart, summary
