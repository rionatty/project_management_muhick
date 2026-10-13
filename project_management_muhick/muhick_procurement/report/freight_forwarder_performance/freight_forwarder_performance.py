# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Each freight forwarder across shipments: planned against actual transit time, how often they
arrive late, and what the freight cost. Helps plan around slow seasons and costly routes."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "freight_forwarder", "label": _("Freight Forwarder"), "fieldtype": "Link", "options": "Supplier", "width": 220},
		{"fieldname": "shipments", "label": _("Shipments"), "fieldtype": "Int", "width": 100},
		{"fieldname": "arrived", "label": _("Arrived"), "fieldtype": "Int", "width": 90},
		{"fieldname": "avg_planned", "label": _("Average Planned Transit (Days)"), "fieldtype": "Float", "precision": 1, "width": 210},
		{"fieldname": "avg_actual", "label": _("Average Actual Transit (Days)"), "fieldtype": "Float", "precision": 1, "width": 210},
		{"fieldname": "avg_delay", "label": _("Average Late Arrival (Days)"), "fieldtype": "Float", "precision": 1, "width": 190},
		{"fieldname": "late", "label": _("Arrived Late"), "fieldtype": "Int", "width": 110},
		{"fieldname": "freight_cost", "label": _("Freight Charges"), "fieldtype": "Currency", "width": 150},
	]
	conditions = {"freight_forwarder": ("is", "set")}
	if filters.from_date and filters.to_date:
		conditions["creation"] = ("between", [filters.from_date, filters.to_date])
	shipments = frappe.get_all(
		"Import Shipment",
		filters=conditions,
		fields=["name", "freight_forwarder", "transit_days_planned", "transit_days_actual", "planned_arrival", "actual_arrival"],
	)
	freight = defaultdict(float)
	if shipments:
		for c in frappe.get_all(
			"Import Shipment Charge",
			filters={"parent": ("in", [s.name for s in shipments]), "charge_type": "Freight"},
			fields=["parent", "amount"],
		):
			freight[c.parent] += flt(c.amount)
	summary = {}
	for s in shipments:
		row = summary.setdefault(
			s.freight_forwarder,
			frappe._dict(freight_forwarder=s.freight_forwarder, shipments=0, arrived=0, late=0, freight_cost=0, planned=[], actual=[], delay=[]),
		)
		row.shipments += 1
		row.freight_cost += freight[s.name]
		if s.transit_days_planned:
			row.planned.append(s.transit_days_planned)
		if s.actual_arrival:
			row.arrived += 1
			if s.transit_days_actual:
				row.actual.append(s.transit_days_actual)
			if s.planned_arrival:
				delay = date_diff(s.actual_arrival, s.planned_arrival)
				row.delay.append(delay)
				row.late += 1 if delay > 0 else 0
	rows = []
	for row in summary.values():
		row.avg_planned = _average(row.planned)
		row.avg_actual = _average(row.actual)
		row.avg_delay = _average(row.delay)
		rows.append(row)
	rows.sort(key=lambda r: (r.avg_delay or 0, r.freight_forwarder))
	return columns, rows


def _average(values):
	return sum(values) / len(values) if values else None
