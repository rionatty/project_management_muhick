# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Proposed valuations from the approved activity plan against what was claimed and certified,
milestone by milestone. Shows revenue that is planned, due, claimed and still to be certified."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

CERTIFIED = ("Certified", "Invoiced", "Paid")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "name", "label": _("Milestone"), "fieldtype": "Link", "options": "Project Milestone", "width": 110},
		{"fieldname": "milestone_name", "label": _("Milestone / Phase"), "fieldtype": "Data", "width": 220},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "percent_complete", "label": _("% Complete"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "planned_end", "label": _("Planned End"), "fieldtype": "Date", "width": 110},
		{"fieldname": "planned_claim_date", "label": _("Planned Claim Date"), "fieldtype": "Date", "width": 130},
		{"fieldname": "planned_valuation", "label": _("Planned Valuation"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "claimed", "label": _("Claimed"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "certified", "label": _("Certified"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "variance", "label": _("Certified Less Planned"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "remark", "label": _("Remark"), "fieldtype": "Data", "width": 160},
	]
	conditions = {"is_billing_milestone": 1}
	if filters.project:
		conditions["project"] = filters.project
	milestones = frappe.get_all(
		"Project Milestone",
		filters=conditions,
		fields=[
			"project", "name", "milestone_name", "status", "percent_complete", "planned_end",
			"planned_claim_date", "planned_valuation",
		],
		order_by="project asc, sequence asc",
	)
	claimed, certified = defaultdict(float), defaultdict(float)
	claim_filters = {"docstatus": 1, "milestone": ("is", "set"), "status": ("!=", "Rejected by Client")}
	if filters.project:
		claim_filters["project"] = filters.project
	for c in frappe.get_all("Project Claim", filters=claim_filters, fields=["milestone", "gross_claim", "certified_amount", "status"]):
		claimed[c.milestone] += flt(c.gross_claim)
		if c.status in CERTIFIED:
			certified[c.milestone] += flt(c.certified_amount)
	today = getdate(nowdate())
	for m in milestones:
		m.claimed = claimed.get(m.name, 0)
		m.certified = certified.get(m.name, 0)
		m.variance = m.certified - flt(m.planned_valuation)
		due = m.planned_claim_date or m.planned_end
		if m.status == "Completed" and not m.claimed:
			m.remark = _("Complete, not yet claimed")
		elif not m.claimed and due and getdate(due) < today:
			m.remark = _("Claim overdue")
		elif m.claimed and not m.certified:
			m.remark = _("Awaiting certificate")
	return columns, milestones
