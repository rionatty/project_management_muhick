# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Retention the clients hold on Muhick, and retention Muhick holds on subcontractors:
held, released, still held, and when the Defects Liability Period ends."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "held_by", "label": _("Retention"), "fieldtype": "Data", "width": 170},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "party", "label": _("Client / Subcontractor"), "fieldtype": "Data", "width": 200},
		{"fieldname": "stage", "label": _("Project Stage"), "fieldtype": "Data", "width": 150},
		{"fieldname": "held", "label": _("Retention Held"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "released", "label": _("Released"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "balance", "label": _("Still Held"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "practical_completion", "label": _("Practical Completion"), "fieldtype": "Date", "width": 140},
		{"fieldname": "dlp_end", "label": _("DLP Ends"), "fieldtype": "Date", "width": 110},
	]
	project_filters = {"project": filters.project} if filters.project else {}
	rows = []
	projects = {
		p.name: p
		for p in frappe.get_all(
			"Project",
			filters={"name": filters.project} if filters.project else {},
			fields=[
				"name", "project_name", "customer", "muhick_stage", "muhick_retention_held",
				"muhick_retention_released", "muhick_practical_completion_date", "muhick_dlp_end_date",
			],
		)
	}
	if (filters.retention or "All") in ("All", "Held by Clients"):
		for p in projects.values():
			if flt(p.muhick_retention_held):
				rows.append(_row(_("Held by client"), p, p.customer, p.muhick_retention_held, p.muhick_retention_released))
	if (filters.retention or "All") in ("All", "Held on Subcontractors"):
		for a in frappe.get_all(
			"Subcontract Agreement",
			filters={"docstatus": 1, "retention_held": (">", 0), **project_filters},
			fields=["project", "supplier_name", "supplier", "retention_held", "retention_released"],
		):
			p = projects.get(a.project) or frappe._dict(name=a.project)
			rows.append(_row(_("Held on subcontractor"), p, a.supplier_name or a.supplier, a.retention_held, a.retention_released))
	if filters.only_outstanding:
		rows = [r for r in rows if r["balance"] > 0.005]
	return columns, rows


def _row(held_by, project, party, held, released):
	return {
		"held_by": held_by,
		"project": project.name,
		"project_name": project.get("project_name"),
		"party": party,
		"stage": project.get("muhick_stage"),
		"held": flt(held),
		"released": flt(released),
		"balance": flt(held) - flt(released),
		"practical_completion": project.get("muhick_practical_completion_date"),
		"dlp_end": project.get("muhick_dlp_end_date"),
	}
