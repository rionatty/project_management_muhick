# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Proposed valuations from the approved activity plan against what was claimed and certified,
phase by phase (billing phases only). Shows revenue that is planned, due, claimed and still to be
certified."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.muhick_projects.utils import phase_done

CERTIFIED = ("Certified", "Invoiced", "Paid")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "name", "label": _("Milestone Task"), "fieldtype": "Link", "options": "Task", "width": 130},
		{"fieldname": "subject", "label": _("Milestone / Phase"), "fieldtype": "Data", "width": 220},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "progress", "label": _("% Complete"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "planned_end", "label": _("Planned End"), "fieldtype": "Date", "width": 110},
		{"fieldname": "muhick_planned_claim_date", "label": _("Planned Claim Date"), "fieldtype": "Date", "width": 130},
		{"fieldname": "muhick_planned_valuation", "label": _("Planned Valuation"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "claimed", "label": _("Claimed"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "certified", "label": _("Certified"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "variance", "label": _("Certified Less Planned"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "remark", "label": _("Remark"), "fieldtype": "Data", "width": 160},
	]
	conditions = {"is_group": 1, "muhick_is_billing_milestone": 1, "status": ("!=", "Cancelled")}
	if filters.project:
		conditions["project"] = filters.project
	phases = frappe.get_all(
		"Task",
		filters=conditions,
		fields=[
			"project", "name", "subject", "status", "progress", "exp_end_date",
			"muhick_planned_claim_date", "muhick_planned_valuation",
		],
		order_by="project asc, exp_start_date asc",
	)
	claimed, certified = defaultdict(float), defaultdict(float)
	claim_filters = {"docstatus": 1, "phase": ("is", "set"), "status": ("!=", "Rejected by Client")}
	if filters.project:
		claim_filters["project"] = filters.project
	for c in frappe.get_all("Project Claim", filters=claim_filters, fields=["phase", "gross_claim", "certified_amount", "status"]):
		claimed[c.phase] += flt(c.gross_claim)
		if c.status in CERTIFIED:
			certified[c.phase] += flt(c.certified_amount)
	today = getdate(nowdate())
	for p in phases:
		p.planned_end = getdate(p.exp_end_date) if p.exp_end_date else None
		p.claimed = claimed.get(p.name, 0)
		p.certified = certified.get(p.name, 0)
		p.variance = p.certified - flt(p.muhick_planned_valuation)
		due = p.muhick_planned_claim_date or p.planned_end
		if phase_done(p) and not p.claimed:
			p.remark = _("Complete, not yet claimed")
		elif not p.claimed and due and getdate(due) < today:
			p.remark = _("Claim overdue")
		elif p.claimed and not p.certified:
			p.remark = _("Awaiting certificate")
	return columns, phases
