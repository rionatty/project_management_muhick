# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Fuel and use of each vehicle over a period: fuellings, litres, cost, distance covered and
kilometres per litre. A falling figure for one vehicle is a prompt to look at it."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "vehicle", "label": _("Vehicle / Equipment"), "fieldtype": "Data", "width": 200},
		{"fieldname": "fuellings", "label": _("Fuellings"), "fieldtype": "Int", "width": 100},
		{"fieldname": "litres", "label": _("Litres"), "fieldtype": "Float", "width": 110},
		{"fieldname": "amount", "label": _("Fuel Cost"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "distance", "label": _("Distance (km)"), "fieldtype": "Int", "width": 130},
		{"fieldname": "km_per_litre", "label": _("km per Litre"), "fieldtype": "Float", "precision": 2, "width": 120},
		{"fieldname": "cost_per_km", "label": _("Fuel Cost per km"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "last_odometer", "label": _("Last Odometer (km)"), "fieldtype": "Int", "width": 150},
		{"fieldname": "last_fuelled", "label": _("Last Fuelled"), "fieldtype": "Date", "width": 110},
	]
	conditions = {"docstatus": 1}
	for field in ("vehicle", "project", "company"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	if filters.from_date and filters.to_date:
		conditions["requisition_date"] = ("between", [filters.from_date, filters.to_date])
	logs = frappe.get_all(
		"Fuel Requisition",
		filters=conditions,
		fields=["vehicle", "equipment_name", "requisition_date", "litres", "amount", "distance", "km_per_litre", "odometer"],
		order_by="requisition_date asc, odometer asc",
	)
	summary = {}
	for log in logs:
		key = log.vehicle or log.equipment_name
		row = summary.setdefault(
			key,
			frappe._dict(vehicle=key, fuellings=0, litres=0, amount=0, distance=0, fuel_for_distance=0, last_odometer=0, last_fuelled=None),
		)
		row.fuellings += 1
		row.litres += flt(log.litres)
		row.amount += flt(log.amount)
		row.distance += int(log.distance or 0)
		if flt(log.km_per_litre):
			# litres that covered this distance (issued at the fuelling before)
			row.fuel_for_distance += flt(log.distance) / flt(log.km_per_litre)
		row.last_odometer = max(row.last_odometer, int(log.odometer or 0))
		row.last_fuelled = log.requisition_date
	rows = list(summary.values())
	for row in rows:
		row.km_per_litre = row.distance / row.fuel_for_distance if row.fuel_for_distance else None
		row.cost_per_km = row.amount / row.distance if row.distance else None
	rows.sort(key=lambda r: -r.amount)
	return columns, rows
