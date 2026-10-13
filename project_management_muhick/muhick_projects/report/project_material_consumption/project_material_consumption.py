# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""For one project, item by item: budgeted, requested, ordered, received, moved to site,
consumed, returned and still in the site store. Answers "was everything supplied to this
project used there?" from the system instead of from memory. "In Site Store" is the book
balance: compare it with a physical count to find losses."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine

QUANTITIES = [
	("budget_qty", "Budgeted"),
	("requested_qty", "Requested"),
	("ordered_qty", "Ordered"),
	("received_qty", "Received"),
	("to_site_qty", "Moved to Site"),
	("consumed_qty", "Consumed"),
	("returned_qty", "Returned from Site"),
	("site_balance", "In Site Store"),
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
		*[{"fieldname": f, "label": _(label), "fieldtype": "Float", "width": 115} for f, label in QUANTITIES],
		{"fieldname": "consumed_value", "label": _("Consumed Value"), "fieldtype": "Currency", "width": 140},
	]
	if not filters.project:
		return columns, []
	project = filters.project
	site = tuple(budget_engine.get_site_warehouses(project)) or ("",)
	data = defaultdict(lambda: defaultdict(float))
	params = {"project": project, "site": site}

	def add(field, query, value_field="qty"):
		for r in frappe.db.sql(query, params, as_dict=True):
			if r.item_code:
				data[r.item_code][field] += flt(r.get(value_field))

	budget = budget_engine.get_approved_budget(project)
	if budget:
		for line in frappe.get_all(
			"Project Budget Line", filters={"parent": budget, "item_code": ("is", "set")}, fields=["item_code", "qty"]
		):
			data[line.item_code]["budget_qty"] += flt(line.qty)

	add(
		"requested_qty",
		"""select i.item_code, sum(i.stock_qty) as qty from `tabMaterial Request Item` i
		inner join `tabMaterial Request` p on p.name = i.parent
		where p.docstatus = 1 and p.status not in ('Stopped', 'Cancelled') and i.project = %(project)s
		group by i.item_code""",
	)
	add(
		"ordered_qty",
		"""select i.item_code, sum(i.stock_qty) as qty from `tabPurchase Order Item` i
		inner join `tabPurchase Order` p on p.name = i.parent
		where p.docstatus = 1 and i.project = %(project)s group by i.item_code""",
	)
	add(
		"received_qty",
		"""select i.item_code, sum(i.stock_qty) as qty from `tabPurchase Receipt Item` i
		inner join `tabPurchase Receipt` p on p.name = i.parent
		where p.docstatus = 1 and i.project = %(project)s group by i.item_code""",
	)
	stock_entry = """select d.item_code, sum(d.transfer_qty) as qty, sum(d.amount) as amount
		from `tabStock Entry Detail` d inner join `tabStock Entry` se on se.name = d.parent
		where se.docstatus = 1 and {condition} group by d.item_code"""
	add(
		"to_site_qty",
		stock_entry.format(
			condition="se.purpose = 'Material Transfer' and d.t_warehouse in %(site)s and ifnull(d.s_warehouse, '') not in %(site)s"
		),
	)
	add(
		"returned_qty",
		stock_entry.format(
			condition="se.purpose = 'Material Transfer' and d.s_warehouse in %(site)s and ifnull(d.t_warehouse, '') not in %(site)s"
		),
	)
	consumed = "se.purpose = 'Material Issue' and ifnull(nullif(d.project, ''), se.project) = %(project)s"
	add("consumed_qty", stock_entry.format(condition=consumed))
	add("consumed_value", stock_entry.format(condition=consumed), "amount")
	add(
		"site_balance",
		"select item_code, sum(actual_qty) as qty from `tabBin` where warehouse in %(site)s group by item_code",
	)

	items = {
		i.name: i
		for i in frappe.get_all("Item", filters={"name": ("in", list(data))}, fields=["name", "item_name", "stock_uom"])
	} if data else {}
	rows = []
	for item_code in sorted(data):
		row = frappe._dict(data[item_code], item_code=item_code)
		item = items.get(item_code)
		row.item_name = item.item_name if item else None
		row.stock_uom = item.stock_uom if item else None
		rows.append(row)
	return columns, rows
