# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every bid (opportunity) with its stage, value, what was spent pursuing it and why it was won or
lost."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt, get_datetime, getdate, nowdate

WON = ("Quotation", "Converted")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Bid"), "fieldtype": "Link", "options": "Opportunity", "width": 140},
		{"fieldname": "customer_name", "label": _("Organisation"), "fieldtype": "Data", "width": 200},
		{"fieldname": "opportunity_type", "label": _("Type of Work"), "fieldtype": "Data", "width": 140},
		{"fieldname": "opportunity_owner", "label": _("Sales Engineer"), "fieldtype": "Link", "options": "User", "width": 160},
		{"fieldname": "sales_stage", "label": _("Stage"), "fieldtype": "Data", "width": 130},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "utm_source", "label": _("Source"), "fieldtype": "Data", "width": 150},
		{"fieldname": "muhick_submission_deadline", "label": _("Deadline"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "muhick_submitted_at", "label": _("Submitted On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "muhick_submission_mode", "label": _("Mode"), "fieldtype": "Data", "width": 90},
		{"fieldname": "acknowledged", "label": _("Acknowledged"), "fieldtype": "Check", "width": 100},
		{"fieldname": "late", "label": _("Late"), "fieldtype": "Check", "width": 60},
		{"fieldname": "days_waiting", "label": _("Days Since Submission"), "fieldtype": "Int", "width": 110},
		{"fieldname": "opportunity_amount", "label": _("Bid Price"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "muhick_margin_percent", "label": _("Margin %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "bid_cost", "label": _("Spent on the Bid"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "muhick_bid_security", "label": _("Bid Security"), "fieldtype": "Link", "options": "Bank Instrument", "width": 130},
		{"fieldname": "security_status", "label": _("Security Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "muhick_outcome_date", "label": _("Outcome Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "outcome", "label": _("Why Won / Lost"), "fieldtype": "Data", "width": 300},
	]
	conditions = {}
	for field in ("status", "sales_stage", "opportunity_owner", "company"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	if filters.from_date and filters.to_date:
		conditions["transaction_date"] = ("between", [filters.from_date, filters.to_date])
	computed = ("bid_cost", "security_status", "outcome", "acknowledged", "late", "days_waiting")
	bids = frappe.get_all(
		"Opportunity",
		filters=conditions,
		fields=[c["fieldname"] for c in columns if c["fieldname"] not in computed] + ["muhick_outcome_notes", "order_lost_reason", "muhick_acknowledgement"],
		order_by="transaction_date desc",
	)
	if not bids:
		return columns, []
	spent = defaultdict(float)
	for r in frappe.get_all(
		"Sales Requisition",
		filters={"opportunity": ("in", [b.name for b in bids]), "docstatus": 1},
		fields=["opportunity", "status", "amount_issued", "amount_spent"],
	):
		# once accounted for, what was actually spent; until then, what was issued
		spent[r.opportunity] += flt(r.amount_spent) if r.status in ("Accounted", "Closed") else flt(r.amount_issued)
	securities = [b.muhick_bid_security for b in bids if b.muhick_bid_security]
	security_status = dict(
		frappe.get_all("Bank Instrument", filters={"name": ("in", securities)}, fields=["name", "status"], as_list=True)
	) if securities else {}
	for b in bids:
		b.bid_cost = spent.get(b.name, 0)
		b.security_status = security_status.get(b.muhick_bid_security)
		b.outcome = b.order_lost_reason if b.status == "Lost" else b.muhick_outcome_notes
		b.acknowledged = 1 if b.muhick_acknowledgement else 0
		submitted, deadline = b.muhick_submitted_at, b.muhick_submission_deadline
		b.late = 1 if submitted and deadline and get_datetime(submitted) > get_datetime(deadline) else 0
		# still waiting for the outcome
		if submitted and b.sales_stage in ("Submitted", "Under Evaluation") and b.status == "Open":
			b.days_waiting = date_diff(nowdate(), getdate(submitted))
	won = sum(1 for b in bids if b.sales_stage == "Awarded" or b.status in WON)
	decided = won + sum(1 for b in bids if b.status == "Lost")
	message = _("{0} bids, {1} decided, {2} won ({3}%).").format(
		len(bids), decided, won, round(won / decided * 100) if decided else 0
	)
	return columns, bids, message
