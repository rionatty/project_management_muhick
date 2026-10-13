# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Purchase price of each item month by month, from approved purchase orders: lowest, average
and highest rate, and the movement against the month before. Shows price patterns for items
bought again and again, such as pipes and fittings."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "month", "label": _("Month"), "fieldtype": "Data", "width": 90},
		{"fieldname": "orders", "label": _("Orders"), "fieldtype": "Int", "width": 80},
		{"fieldname": "qty", "label": _("Qty Bought"), "fieldtype": "Float", "width": 110},
		{"fieldname": "min_rate", "label": _("Lowest Rate"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "avg_rate", "label": _("Average Rate"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "max_rate", "label": _("Highest Rate"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "change_percent", "label": _("Change on Previous Month %"), "fieldtype": "Percent", "width": 190},
	]
	conditions = ["po.docstatus = 1", "po.transaction_date between %(from_date)s and %(to_date)s"]
	params = {"from_date": filters.from_date, "to_date": filters.to_date}
	for field, column in (("item_code", "poi.item_code"), ("item_group", "poi.item_group"), ("supplier", "po.supplier")):
		if filters.get(field):
			conditions.append(f"{column} = %({field})s")
			params[field] = filters.get(field)
	if not (filters.from_date and filters.to_date):
		return columns, []
	rows = frappe.db.sql(
		f"""
		select poi.item_code, max(poi.item_name) as item_name, date_format(po.transaction_date, '%%Y-%%m') as month,
			count(distinct po.name) as orders, sum(poi.stock_qty) as qty,
			min(poi.base_rate) as min_rate, max(poi.base_rate) as max_rate,
			sum(poi.base_net_amount) / nullif(sum(poi.qty), 0) as avg_rate
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where {" and ".join(conditions)}
		group by poi.item_code, date_format(po.transaction_date, '%%Y-%%m')
		order by poi.item_code, month
		""",
		params,
		as_dict=True,
	)
	previous = {}
	for r in rows:
		last = previous.get(r.item_code)
		r.change_percent = (flt(r.avg_rate) - last) / last * 100 if last else None
		previous[r.item_code] = flt(r.avg_rate)
	return columns, rows
