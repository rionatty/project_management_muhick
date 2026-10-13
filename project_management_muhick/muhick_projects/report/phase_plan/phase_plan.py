# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Phase plan of a project: each phase with its dates, progress, target valuation, and the
materials, works and labour planned for it, against what has been requested so far. Shows which
phase the project is in and what the next one needs."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine

DONE = ("Completed", "Claimed", "Certified")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sequence", "label": _("No."), "fieldtype": "Int", "width": 60},
		{"fieldname": "name", "label": _("Milestone"), "fieldtype": "Link", "options": "Project Milestone", "width": 110},
		{"fieldname": "milestone_name", "label": _("Phase"), "fieldtype": "Data", "width": 220},
		{"fieldname": "phase", "label": _("Position"), "fieldtype": "Data", "width": 110},
		{"fieldname": "planned_start", "label": _("Planned Start"), "fieldtype": "Date", "width": 110},
		{"fieldname": "planned_end", "label": _("Planned End"), "fieldtype": "Date", "width": 110},
		{"fieldname": "percent_complete", "label": _("% Complete"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "planned_valuation", "label": _("Target Valuation"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "materials_budget", "label": _("Materials Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "works_budget", "label": _("Works Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "other_budget", "label": _("Administrative Budget"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "labour_scheduled", "label": _("Labour Scheduled"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "materials_requested", "label": _("Materials Requested"), "fieldtype": "Currency", "width": 150},
	]
	if not filters.project:
		return columns, []
	milestones = frappe.get_all(
		"Project Milestone",
		filters={"project": filters.project},
		fields=["name", "sequence", "milestone_name", "status", "planned_start", "planned_end", "percent_complete", "planned_valuation"],
		order_by="sequence asc, planned_start asc",
	)
	budget = defaultdict(lambda: defaultdict(float))
	approved = budget_engine.get_approved_budget(filters.project)
	if approved:
		for line in frappe.get_all(
			"Project Budget Line",
			filters={"parent": approved, "milestone": ("is", "set")},
			fields=["milestone", "budget_section", "amount"],
		):
			budget[line.milestone][line.budget_section] += flt(line.amount)
	labour = defaultdict(float)
	for s in frappe.get_all(
		"Labour Schedule",
		filters={"project": filters.project, "docstatus": 1, "milestone": ("is", "set")},
		fields=["milestone", "total_amount"],
	):
		labour[s.milestone] += flt(s.total_amount)
	requested = defaultdict(float)
	for r in frappe.db.sql(
		"""
		select mr.muhick_milestone as milestone, sum(mri.amount) as amount
		from `tabMaterial Request Item` mri inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus = 1 and mr.muhick_project = %s and ifnull(mr.muhick_milestone, '') != ''
		group by mr.muhick_milestone
		""",
		(filters.project,),
		as_dict=True,
	):
		requested[r.milestone] = flt(r.amount)
	current = next((m.name for m in milestones if m.status not in DONE), None)
	for m in milestones:
		m.phase = _("Current") if m.name == current else _("Done") if m.status in DONE else _("Upcoming")
		m.materials_budget = budget[m.name]["Materials"]
		m.works_budget = budget[m.name]["Works"]
		m.other_budget = budget[m.name]["Administrative"]
		m.labour_scheduled = labour[m.name]
		m.materials_requested = requested[m.name]
	return columns, milestones
