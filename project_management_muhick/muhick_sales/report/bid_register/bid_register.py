# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every bid with its status, value, what was spent pursuing it and why it was won or lost."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Bid"), "fieldtype": "Link", "options": "Bid", "width": 130},
		{"fieldname": "title", "label": _("Bid / Tender"), "fieldtype": "Data", "width": 220},
		{"fieldname": "procuring_entity", "label": _("Procuring Entity"), "fieldtype": "Data", "width": 180},
		{"fieldname": "assigned_to", "label": _("Sales Engineer"), "fieldtype": "Link", "options": "User", "width": 160},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "lead_source", "label": _("Source"), "fieldtype": "Data", "width": 150},
		{"fieldname": "submission_deadline", "label": _("Deadline"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "submitted_on", "label": _("Submitted On"), "fieldtype": "Date", "width": 110},
		{"fieldname": "bid_price", "label": _("Bid Price"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "margin_percent", "label": _("Margin %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "bid_cost", "label": _("Spent on the Bid"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "bid_security", "label": _("Bid Security"), "fieldtype": "Link", "options": "Bank Instrument", "width": 130},
		{"fieldname": "security_status", "label": _("Security Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "outcome_date", "label": _("Outcome Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "outcome_reason", "label": _("Why Won / Lost"), "fieldtype": "Data", "width": 300},
	]
	conditions = {}
	for field in ("status", "assigned_to", "company"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	if filters.from_date and filters.to_date:
		conditions["creation"] = ("between", [filters.from_date, filters.to_date])
	bids = frappe.get_all("Bid", filters=conditions, fields=[c["fieldname"] for c in columns if c["fieldname"] not in ("bid_cost", "security_status")], order_by="creation desc")
	if not bids:
		return columns, []
	spent = defaultdict(float)
	for r in frappe.get_all(
		"Sales Requisition",
		filters={"bid": ("in", [b.name for b in bids]), "docstatus": 1},
		fields=["bid", "status", "amount_issued", "amount_spent"],
	):
		# once accounted for, what was actually spent; until then, what was issued
		spent[r.bid] += flt(r.amount_spent) if r.status in ("Accounted", "Closed") else flt(r.amount_issued)
	securities = [b.bid_security for b in bids if b.bid_security]
	security_status = dict(
		frappe.get_all("Bank Instrument", filters={"name": ("in", securities)}, fields=["name", "status"], as_list=True)
	) if securities else {}
	for b in bids:
		b.bid_cost = spent.get(b.name, 0)
		b.security_status = security_status.get(b.bid_security)
	decided = [b for b in bids if b.status in ("Won", "Lost")]
	won = sum(1 for b in decided if b.status == "Won")
	message = _("{0} bids, {1} decided, {2} won ({3}%).").format(
		len(bids), len(decided), won, round(won / len(decided) * 100) if decided else 0
	)
	return columns, bids, message
