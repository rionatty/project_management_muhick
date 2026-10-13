# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bank facilities: the limit, what is running against it and what is left. The second view
lists the instruments themselves with their end dates and the next quarterly fee."""

import frappe
from frappe import _
from frappe.utils import flt

RUNNING = ("Requested", "Active", "Cancellation Requested")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if (filters.view or "Facilities") == "Instruments":
		return instruments(filters)
	return facilities(filters)


def facilities(filters):
	columns = [
		{"fieldname": "name", "label": _("Facility"), "fieldtype": "Link", "options": "Bank Facility", "width": 220},
		{"fieldname": "bank", "label": _("Bank"), "fieldtype": "Link", "options": "Bank", "width": 160},
		{"fieldname": "facility_type", "label": _("Type"), "fieldtype": "Data", "width": 170},
		{"fieldname": "limit_amount", "label": _("Limit"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "utilised", "label": _("In Use"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "available", "label": _("Available"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "running", "label": _("Instruments Running"), "fieldtype": "Int", "width": 150},
		{"fieldname": "fees_per_quarter", "label": _("Fees per Quarter"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "review_date", "label": _("Review / Expiry"), "fieldtype": "Date", "width": 120},
	]
	conditions = {"disabled": 0}
	if filters.company:
		conditions["company"] = filters.company
	rows = frappe.get_all(
		"Bank Facility", filters=conditions, fields=["name", "bank", "facility_type", "limit_amount", "review_date"], order_by="bank asc"
	)
	for row in rows:
		running = frappe.get_all(
			"Bank Instrument",
			filters={"bank_facility": row.name, "status": ("in", RUNNING)},
			fields=["amount", "quarterly_fee"],
		)
		# counted live so the report is right even if a stored figure is stale
		row.utilised = sum(flt(i.amount) for i in running)
		row.available = flt(row.limit_amount) - row.utilised
		row.running = len(running)
		row.fees_per_quarter = sum(flt(i.quarterly_fee) for i in running)
	return columns, rows


def instruments(filters):
	columns = [
		{"fieldname": "name", "label": _("Instrument"), "fieldtype": "Link", "options": "Bank Instrument", "width": 130},
		{"fieldname": "title", "label": _("Description"), "fieldtype": "Data", "width": 230},
		{"fieldname": "instrument_type", "label": _("Type"), "fieldtype": "Data", "width": 170},
		{"fieldname": "bank_facility", "label": _("Facility"), "fieldtype": "Link", "options": "Bank Facility", "width": 180},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 160},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "beneficiary", "label": _("Beneficiary"), "fieldtype": "Data", "width": 180},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "issue_date", "label": _("Start"), "fieldtype": "Date", "width": 100},
		{"fieldname": "expiry_date", "label": _("End"), "fieldtype": "Date", "width": 100},
		{"fieldname": "quarterly_fee", "label": _("Fee per Quarter"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "fees_charged", "label": _("Fees Charged"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "next_fee_due", "label": _("Next Fee Due"), "fieldtype": "Date", "width": 120},
	]
	conditions = {}
	if filters.company:
		conditions["company"] = filters.company
	if not filters.include_closed:
		conditions["status"] = ("in", RUNNING)
	rows = frappe.get_all(
		"Bank Instrument", filters=conditions, fields=[c["fieldname"] for c in columns], order_by="expiry_date asc"
	)
	return columns, rows
