# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every bid (opportunity) with its status and how long it has been in it, its value and margin, what
was spent pursuing it, its outcome report and why it was won or lost, and the project a won bid
became."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, get_datetime, getdate, nowdate

from project_management_muhick.muhick_sales.bids import bid_spent


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Bid"), "fieldtype": "Link", "options": "Opportunity", "width": 140},
		{"fieldname": "customer_name", "label": _("Organisation"), "fieldtype": "Data", "width": 200},
		{"fieldname": "opportunity_type", "label": _("Type of Work"), "fieldtype": "Data", "width": 140},
		{"fieldname": "opportunity_owner", "label": _("Sales Engineer"), "fieldtype": "Link", "options": "User", "width": 160},
		{"fieldname": "status", "label": _("Opportunity Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "sales_stage", "label": _("Bid Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "days_in_status", "label": _("Days in Status"), "fieldtype": "Int", "width": 90},
		{"fieldname": "muhick_progress", "label": _("Progress %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "utm_source", "label": _("Source"), "fieldtype": "Data", "width": 150},
		{"fieldname": "muhick_submission_deadline", "label": _("Deadline"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "documents_ready", "label": _("Documents Ready"), "fieldtype": "Data", "width": 110},
		{"fieldname": "muhick_submitted_at", "label": _("Submitted On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "muhick_submission_mode", "label": _("Mode"), "fieldtype": "Data", "width": 90},
		{"fieldname": "acknowledged", "label": _("Acknowledged"), "fieldtype": "Check", "width": 100},
		{"fieldname": "late", "label": _("Late"), "fieldtype": "Check", "width": 60},
		{"fieldname": "days_waiting", "label": _("Days Since Submission"), "fieldtype": "Int", "width": 110},
		{"fieldname": "expected_closing", "label": _("Expected Award"), "fieldtype": "Date", "width": 110},
		{"fieldname": "opportunity_amount", "label": _("Bid Price"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "muhick_margin_percent", "label": _("Margin at Bid %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "gross_margin", "label": _("Margin at Award %"), "fieldtype": "Percent", "width": 110},
		{"fieldname": "bid_cost", "label": _("Spent on the Bid"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "project", "label": _("Carried to Project"), "fieldtype": "Link", "options": "Project", "width": 140},
		{"fieldname": "muhick_bid_security", "label": _("Bid Security"), "fieldtype": "Link", "options": "Bank Instrument", "width": 130},
		{"fieldname": "security_status", "label": _("Security Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "outcome_report", "label": _("Outcome Report"), "fieldtype": "Link", "options": "Bid Outcome", "width": 140},
		{"fieldname": "muhick_outcome_date", "label": _("Outcome Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "outcome", "label": _("Why Won / Lost"), "fieldtype": "Data", "width": 300},
	]
	conditions = {}
	for field in ("status", "sales_stage", "opportunity_owner", "company"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	if filters.from_date and filters.to_date:
		conditions["transaction_date"] = ("between", [filters.from_date, filters.to_date])
	computed = (
		"days_in_status", "documents_ready", "acknowledged", "late", "days_waiting", "gross_margin", "bid_cost", "project",
		"security_status", "outcome_report", "outcome",
	)
	bids = frappe.get_all(
		"Opportunity",
		filters=conditions,
		fields=[c["fieldname"] for c in columns if c["fieldname"] not in computed]
		+ ["muhick_stage_since", "muhick_outcome_notes", "order_lost_reason", "muhick_acknowledgement"],
		order_by="transaction_date desc",
	)
	if not bids:
		return columns, []
	names = [b.name for b in bids]
	spent = bid_spent(names)
	securities = [b.muhick_bid_security for b in bids if b.muhick_bid_security]
	security_status = dict(
		frappe.get_all("Bank Instrument", filters={"name": ("in", securities)}, fields=["name", "status"], as_list=True)
	) if securities else {}
	# the latest outcome report of each bid that is not cancelled
	reports = {
		r.opportunity: r
		for r in frappe.get_all(
			"Bid Outcome",
			filters={"opportunity": ("in", names), "docstatus": ("<", 2)},
			fields=["name", "opportunity", "docstatus", "outcome", "gross_margin"],
			order_by="creation asc",
		)
	}
	# the first project made from each bid, which carries its costs
	projects = dict(
		frappe.get_all(
			"Project Handover",
			filters={"opportunity": ("in", names), "docstatus": 1},
			fields=["opportunity", "project"],
			order_by="creation desc",
			as_list=True,
		)
	)
	# documents ready of those on each bid's checklist
	checklist = defaultdict(lambda: [0, 0])
	for row in frappe.get_all(
		"Bid Checklist Item", filters={"parent": ("in", names), "parenttype": "Opportunity"}, fields=["parent", "status"]
	):
		checklist[row.parent][1] += 1
		checklist[row.parent][0] += 1 if row.status == "Ready" else 0
	today = getdate(nowdate())
	for b in bids:
		b.days_in_status = date_diff(today, getdate(b.muhick_stage_since)) if b.muhick_stage_since else None
		if b.name in checklist:
			b.documents_ready = _("{0} of {1}").format(*checklist[b.name])
		b.bid_cost = spent.get(b.name, 0)
		report = reports.get(b.name)
		b.outcome_report = report.name if report else None
		if report and report.docstatus == 1 and report.outcome == "Won":
			b.gross_margin = report.gross_margin
		b.project = projects.get(b.name) if b.sales_stage == "Won" else None
		b.security_status = security_status.get(b.muhick_bid_security)
		b.outcome = b.order_lost_reason if b.status == "Lost" else b.muhick_outcome_notes
		b.acknowledged = 1 if b.muhick_acknowledgement else 0
		submitted, deadline = b.muhick_submitted_at, b.muhick_submission_deadline
		b.late = 1 if submitted and deadline and get_datetime(submitted) > get_datetime(deadline) else 0
		# still waiting for the outcome
		if submitted and b.sales_stage in ("Submitted", "Under Evaluation", "Outcome Pending Approval"):
			b.days_waiting = date_diff(today, getdate(submitted))
	won = sum(1 for b in bids if b.sales_stage == "Won")
	decided = won + sum(1 for b in bids if b.sales_stage == "Lost")
	message = _("{0} bids, {1} decided, {2} won ({3}%).").format(
		len(bids), decided, won, round(won / decided * 100) if decided else 0
	)
	return columns, bids, message
