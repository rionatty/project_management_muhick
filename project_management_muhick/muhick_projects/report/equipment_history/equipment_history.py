# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Each piece of equipment over a period: fuel used and fuel per hour, services, breakdowns and
what repairs and spares have cost. Rising fuel per hour or repeated breakdowns point to a machine
that needs servicing or replacing."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "equipment_name", "label": _("Equipment / Tool"), "fieldtype": "Data", "width": 220},
		{"fieldname": "serial_no", "label": _("Serial No."), "fieldtype": "Data", "width": 130},
		{"fieldname": "fuel_litres", "label": _("Fuel (Litres)"), "fieldtype": "Float", "width": 110},
		{"fieldname": "hours_run", "label": _("Hours Run"), "fieldtype": "Float", "width": 100},
		{"fieldname": "litres_per_hour", "label": _("Litres per Hour"), "fieldtype": "Float", "precision": 2, "width": 120},
		{"fieldname": "fuel_cost", "label": _("Fuel Cost"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "services", "label": _("Services"), "fieldtype": "Int", "width": 90},
		{"fieldname": "service_cost", "label": _("Service Cost"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "breakdowns", "label": _("Breakdowns"), "fieldtype": "Int", "width": 100},
		{"fieldname": "repair_cost", "label": _("Repairs and Spares"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "total_cost", "label": _("Total Cost"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "last_service", "label": _("Last Service"), "fieldtype": "Date", "width": 110},
		{"fieldname": "next_service_date", "label": _("Next Service Due"), "fieldtype": "Date", "width": 130},
	]
	conditions = {}
	if filters.project:
		conditions["project"] = filters.project
	if filters.from_date and filters.to_date:
		conditions["log_date"] = ("between", [filters.from_date, filters.to_date])
	logs = frappe.get_all(
		"Equipment Log",
		filters=conditions,
		fields=["equipment_name", "serial_no", "log_type", "log_date", "fuel_litres", "hours_run", "cost", "next_service_date"],
		order_by="log_date asc",
	)
	summary = {}
	for log in logs:
		row = summary.setdefault(
			(log.equipment_name, log.serial_no or ""),
			frappe._dict(
				equipment_name=log.equipment_name, serial_no=log.serial_no, fuel_litres=0, hours_run=0, fuel_cost=0,
				services=0, service_cost=0, breakdowns=0, repair_cost=0, total_cost=0, last_service=None, next_service_date=None,
			),
		)
		cost = flt(log.cost)
		row.total_cost += cost
		if log.log_type == "Fuel":
			row.fuel_litres += flt(log.fuel_litres)
			row.hours_run += flt(log.hours_run)
			row.fuel_cost += cost
		elif log.log_type == "Service":
			row.services += 1
			row.service_cost += cost
			row.last_service = log.log_date
			row.next_service_date = log.next_service_date or row.next_service_date
		else:
			row.breakdowns += 1 if log.log_type == "Breakdown" else 0
			row.repair_cost += cost
	rows = list(summary.values())
	for row in rows:
		row.litres_per_hour = row.fuel_litres / row.hours_run if row.hours_run else None
	rows.sort(key=lambda r: -r.total_cost)
	return columns, rows
