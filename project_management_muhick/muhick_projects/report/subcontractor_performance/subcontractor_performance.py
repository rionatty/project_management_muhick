# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Each subcontractor's history across projects: work awarded and certified, ratings given at
the close of each subcontract, and how many subcontracts are running now. This keeps the
knowledge in the system instead of in the memory of whoever managed the last project."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

RATINGS = ("rating_quality", "rating_timeliness", "rating_safety", "overall_rating")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "supplier", "label": _("Subcontractor"), "fieldtype": "Link", "options": "Supplier", "width": 150},
		{"fieldname": "supplier_name", "label": _("Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "agreements", "label": _("Subcontracts"), "fieldtype": "Int", "width": 110},
		{"fieldname": "active", "label": _("Active Now"), "fieldtype": "Int", "width": 100},
		{"fieldname": "contract_amount", "label": _("Total Awarded"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "certified", "label": _("Total Certified"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "rated", "label": _("Rated Subcontracts"), "fieldtype": "Int", "width": 130},
		{"fieldname": "rating_quality", "label": _("Quality (of 5)"), "fieldtype": "Float", "precision": 1, "width": 110},
		{"fieldname": "rating_timeliness", "label": _("Timeliness (of 5)"), "fieldtype": "Float", "precision": 1, "width": 130},
		{"fieldname": "rating_safety", "label": _("Safety (of 5)"), "fieldtype": "Float", "precision": 1, "width": 110},
		{"fieldname": "overall_rating", "label": _("Overall (of 5)"), "fieldtype": "Float", "precision": 1, "width": 110},
	]
	conditions = {"docstatus": 1}
	if filters.supplier:
		conditions["supplier"] = filters.supplier
	agreements = frappe.get_all(
		"Subcontract Agreement",
		filters=conditions,
		fields=["supplier", "supplier_name", "status", "contract_amount", "certified_to_date", *RATINGS],
	)
	summary = {}
	scores = defaultdict(lambda: defaultdict(list))
	for a in agreements:
		row = summary.setdefault(
			a.supplier,
			frappe._dict(supplier=a.supplier, supplier_name=a.supplier_name, agreements=0, active=0, contract_amount=0, certified=0, rated=0),
		)
		row.agreements += 1
		row.active += 1 if a.status == "Active" else 0
		row.contract_amount += flt(a.contract_amount)
		row.certified += flt(a.certified_to_date)
		if flt(a.overall_rating):
			row.rated += 1
			for field in RATINGS:
				if flt(a.get(field)):
					# a Rating field stores 0..1; show it as stars out of 5
					scores[a.supplier][field].append(flt(a.get(field)) * 5)
	rows = []
	for supplier, row in summary.items():
		for field in RATINGS:
			values = scores[supplier][field]
			row[field] = sum(values) / len(values) if values else None
		rows.append(row)
	rows.sort(key=lambda r: (-(r.overall_rating or 0), r.supplier_name or ""))
	return columns, rows
