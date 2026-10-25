# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid's BOQ against the prices its suppliers quoted: each supplier's latest price per line side by
side, the lowest picked out, and the gross profit at the lowest prices after what was spent on the
bid. A line no supplier has quoted is costed at the item's last purchase price."""

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_sales.bids import (
	bid_spent, boq_factor, boq_quotes, last_purchase_rate, latest_by_supplier, lowest,
)
from project_management_muhick.utils import calc


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.opportunity:
		return [], []
	bid = frappe.get_doc("Opportunity", filters.opportunity)
	bid.check_permission("read")
	offers = {item: latest_by_supplier(quotes, filters.include_expired) for item, quotes in boq_quotes(bid.name).items()}
	suppliers = sorted({supplier for by_supplier in offers.values() for supplier in by_supplier})
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 140},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Link", "options": "Task Type", "width": 120},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 70},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "bid_rate", "label": _("Bid Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "bid_amount", "label": _("Bid Amount"), "fieldtype": "Currency", "width": 130},
	]
	columns += [
		{"fieldname": f"supplier_{i}", "label": supplier, "fieldtype": "Currency", "width": 130} for i, supplier in enumerate(suppliers)
	]
	columns += [
		{"fieldname": "lowest_rate", "label": _("Lowest Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "lowest_supplier", "label": _("Lowest From"), "fieldtype": "Data", "width": 160},
		{"fieldname": "cost", "label": _("Cost at the Lowest"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "margin", "label": _("Margin"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "margin_percent", "label": _("Margin %"), "fieldtype": "Percent", "width": 90},
	]
	rows, unquoted = [], 0
	for item in bid.get("items") or []:
		factor = boq_factor(item.item_code, item.uom)
		by_supplier = offers.get(item.item_code, {})
		row = frappe._dict(
			item_code=item.item_code, item_name=item.item_name, stage=item.get("muhick_stage"), qty=item.qty, uom=item.uom,
			bid_rate=item.base_rate, bid_amount=item.base_amount,
		)
		for i, supplier in enumerate(suppliers):
			if supplier in by_supplier:
				row[f"supplier_{i}"] = by_supplier[supplier].stock_rate * factor
		best = lowest(list(by_supplier.values()))
		if best:
			row.lowest_rate, row.lowest_supplier = best.stock_rate * factor, best.supplier
		else:
			unquoted += 1
			row.lowest_rate = last_purchase_rate(item.item_code) * factor
			row.lowest_supplier = _("Last purchase price") if row.lowest_rate else _("Not quoted")
		row.cost = flt(item.qty) * flt(row.lowest_rate)
		row.margin = flt(item.base_amount) - row.cost
		row.margin_percent = calc.margin_percent(item.base_amount, row.cost)
		rows.append(row)

	bid_value = sum(flt(r.bid_amount) for r in rows)
	cost = sum(flt(r.cost) for r in rows)
	spent = bid_spent([bid.name]).get(bid.name, 0)
	profit = bid_value - cost - spent
	margin = calc.margin_percent(bid_value, cost + spent)
	summary = [
		{"value": bid_value, "label": _("Bid Value"), "datatype": "Currency", "indicator": "Blue"},
		{"value": cost, "label": _("Cost at the Lowest Prices"), "datatype": "Currency", "indicator": "Grey"},
		{"value": spent, "label": _("Spent on the Bid"), "datatype": "Currency", "indicator": "Grey"},
		{"value": profit, "label": _("Gross Profit"), "datatype": "Currency", "indicator": "Green" if profit >= 0 else "Red"},
		{"value": margin, "label": _("Gross Profit Margin %"), "datatype": "Percent", "indicator": "Green" if margin >= 0 else "Red"},
	]
	if suppliers:
		message = _("{0} of {1} BOQ lines quoted, by {2} supplier(s).").format(len(rows) - unquoted, len(rows), len(suppliers))
	else:
		message = _("No supplier has quoted for this bid yet: raise a request for quotation from the opportunity (Create > Request For Quotation).")
	return columns, rows, message, None, summary
