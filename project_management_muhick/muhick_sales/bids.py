# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""What a bid cost to pursue, and its BOQ priced at the suppliers' quotations.

Spent on a bid: its sales requisitions (what was spent once accounted for, until then what was
issued), the funds issued for its bid security, and the bid security's quarterly fees after the
first, which the bid security request already paid for. The project a won bid becomes carries these
costs as its own."""

from collections import defaultdict

import frappe
from frappe.utils import flt, getdate, nowdate

# a requisition that has been accounted for, and one that was never paid
ACCOUNTED = ("Accounted", "Closed")
DROPPED = ("Rejected", "Cancelled")


def bid_costs_position(opportunities) -> dict:
	"""{opportunity: {committed, actual, paid}} for what pursuing each bid cost: committed once
	approved, actual once spent, paid as the money went out."""
	names = list({o for o in opportunities if o})
	position = {name: {"committed": 0.0, "actual": 0.0, "paid": 0.0} for name in names}
	if not names:
		return position
	for r in frappe.get_all(
		"Sales Requisition",
		filters={"opportunity": ("in", names), "docstatus": 1, "status": ("not in", DROPPED)},
		fields=["opportunity", "status", "total_amount", "amount_issued", "amount_spent"],
	):
		p = position[r.opportunity]
		if r.status in ACCOUNTED:
			for key in p:
				p[key] += flt(r.amount_spent)
		else:
			p["committed"] += flt(r.total_amount)
			p["paid"] += flt(r.amount_issued)
	for r in frappe.get_all(
		"Bid Security Request",
		filters={"opportunity": ("in", names), "docstatus": 1},
		fields=["opportunity", "funds_required", "amount_issued"],
	):
		p = position[r.opportunity]
		p["committed"] += max(flt(r.funds_required), flt(r.amount_issued))
		p["actual"] += flt(r.amount_issued)
		p["paid"] += flt(r.amount_issued)
	for opportunity, amount in frappe.db.sql(
		"""
		select instrument.opportunity, sum(fee.amount)
		from `tabBank Instrument Fee` fee
		inner join `tabBank Instrument` instrument on instrument.name = fee.parent
		where instrument.opportunity in %(names)s and instrument.instrument_type = 'Bid Security' and fee.paid = 1
			and (ifnull(instrument.bid_security_request, '') = '' or fee.due_date > instrument.issue_date)
		group by instrument.opportunity
		""",
		{"names": names},
	):
		for key in position[opportunity]:
			position[opportunity][key] += flt(amount)
	return position


def bid_spent(opportunities) -> dict:
	"""{opportunity: what was spent pursuing it}."""
	return {name: p["paid"] for name, p in bid_costs_position(opportunities).items()}


def project_bid(project) -> str | None:
	"""The won bid a project came from: through its accepted handover, or its sales order's
	quotation. A bid split into several projects is carried by the first of them."""
	opportunity = frappe.db.get_value("Project Handover", {"project": project, "docstatus": 1}, "opportunity")
	if not opportunity:
		sales_order = frappe.db.get_value("Project", project, "sales_order")
		quotation = sales_order and frappe.db.get_value(
			"Sales Order Item", {"parent": sales_order, "prevdoc_docname": ("is", "set")}, "prevdoc_docname"
		)
		opportunity = quotation and frappe.db.get_value("Quotation", quotation, "opportunity")
	if not opportunity:
		return None
	first = frappe.db.get_value(
		"Project Handover", {"opportunity": opportunity, "docstatus": 1}, "project", order_by="creation asc"
	)
	return opportunity if first in (None, project) else None


def boq_quotes(opportunity) -> dict:
	"""{item_code: [quote]} from the supplier quotations of a bid, latest first. Each quote carries its
	price per stock unit in the company currency (stock_rate) and whether it has expired."""
	today = getdate(nowdate())
	quotes = defaultdict(list)
	for q in frappe.db.sql(
		"""
		select quotation.name as supplier_quotation, quotation.supplier, quotation.transaction_date,
			quotation.valid_till, quotation.status, item.item_code, item.base_net_rate, item.conversion_factor
		from `tabSupplier Quotation Item` item
		inner join `tabSupplier Quotation` quotation on quotation.name = item.parent
		where quotation.opportunity = %(opportunity)s and quotation.docstatus < 2
			and quotation.status not in ('Stopped', 'Cancelled')
		order by quotation.transaction_date desc, quotation.creation desc
		""",
		{"opportunity": opportunity},
		as_dict=True,
	):
		q.stock_rate = flt(q.base_net_rate) / (flt(q.conversion_factor) or 1)
		q.expired = q.status == "Expired" or bool(q.valid_till and getdate(q.valid_till) < today)
		quotes[q.item_code].append(q)
	return quotes


def latest_by_supplier(quotes, include_expired=False) -> dict:
	"""{supplier: their latest quote} among one item's quotes."""
	latest = {}
	for q in quotes:
		if (include_expired or not q.expired) and q.supplier not in latest:
			latest[q.supplier] = q
	return latest


def lowest(quotes):
	"""The cheapest of some quotes, or None."""
	return min(quotes, key=lambda q: q.stock_rate) if quotes else None


def boq_factor(item_code, uom) -> float:
	"""Stock units in one unit of a BOQ line's UOM."""
	if not uom or uom == frappe.get_cached_value("Item", item_code, "stock_uom"):
		return 1.0
	return flt(frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor")) or 1.0


def last_purchase_rate(item_code) -> float:
	"""The item's last purchase price per stock unit: the cost of a line no supplier has quoted."""
	return flt(frappe.get_cached_value("Item", item_code, "last_purchase_rate"))
