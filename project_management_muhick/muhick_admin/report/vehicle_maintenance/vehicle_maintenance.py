# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Servicing and repairs of each vehicle: what was done, what it cost against the estimate, and
when the next service falls due."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Request"), "fieldtype": "Link", "options": "Vehicle Service Request", "width": 150},
		{"fieldname": "vehicle", "label": _("Vehicle"), "fieldtype": "Link", "options": "Vehicle", "width": 130},
		{"fieldname": "service_type", "label": _("Service Type"), "fieldtype": "Data", "width": 150},
		{"fieldname": "request_date", "label": _("Requested"), "fieldtype": "Date", "width": 105},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "description", "label": _("Work"), "fieldtype": "Data", "width": 260},
		{"fieldname": "supplier", "label": _("Garage"), "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"fieldname": "odometer", "label": _("Odometer (km)"), "fieldtype": "Int", "width": 120},
		{"fieldname": "estimated_cost", "label": _("Estimated"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "actual_cost", "label": _("Actual"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "completed_on", "label": _("Completed"), "fieldtype": "Date", "width": 105},
		{"fieldname": "next_service_date", "label": _("Next Service Due"), "fieldtype": "Date", "width": 130},
		{"fieldname": "due", "label": _("Service Due"), "fieldtype": "Data", "width": 110},
	]
	conditions = {"docstatus": 1}
	for field in ("vehicle", "status", "company"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	if filters.from_date and filters.to_date:
		conditions["request_date"] = ("between", [filters.from_date, filters.to_date])
	rows = frappe.get_all(
		"Vehicle Service Request",
		filters=conditions,
		fields=[c["fieldname"] for c in columns if c["fieldname"] != "due"],
		order_by="vehicle asc, request_date desc",
	)
	today = getdate(nowdate())
	latest = set()
	for row in rows:
		# only the most recent service of a vehicle says when the next one is due
		if row.vehicle not in latest and row.next_service_date:
			latest.add(row.vehicle)
			row.due = _("Overdue") if getdate(row.next_service_date) < today else ""
		row.actual_cost = flt(row.actual_cost)
	return columns, rows
