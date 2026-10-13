# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every project on one line for management: stage (running or in its Defects Liability Period),
contract value, certified work, retention, budget, commitments and forecast margin."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "customer", "label": _("Client"), "fieldtype": "Link", "options": "Customer", "width": 160},
		{"fieldname": "muhick_stage", "label": _("Stage"), "fieldtype": "Data", "width": 150},
		{"fieldname": "muhick_project_manager", "label": _("Project Manager"), "fieldtype": "Link", "options": "User", "width": 160},
		{"fieldname": "percent_complete", "label": _("% Complete"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "revised_contract", "label": _("Revised Contract Value"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "certified", "label": _("Certified to Date"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "percent_certified", "label": _("% Certified"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "retention_balance", "label": _("Retention Held"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "current_budget", "label": _("Current Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "committed", "label": _("Committed"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "actual", "label": _("Actual Cost"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "available", "label": _("Available Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "forecast_final_cost", "label": _("Forecast Final Cost"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "forecast_margin", "label": _("Forecast Margin"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "muhick_dlp_end_date", "label": _("DLP Ends"), "fieldtype": "Date", "width": 110},
	]
	conditions = {}
	if filters.company:
		conditions["company"] = filters.company
	if filters.stage:
		conditions["muhick_stage"] = filters.stage
	if not filters.include_closed:
		conditions["status"] = ("!=", "Cancelled")
	projects = frappe.get_all(
		"Project",
		filters=conditions,
		fields=[
			"name", "project_name", "customer", "muhick_stage", "muhick_project_manager", "percent_complete",
			"muhick_contract_value", "muhick_approved_variations", "muhick_certified_to_date",
			"muhick_retention_held", "muhick_retention_released", "muhick_dlp_end_date",
		],
		order_by="muhick_stage asc, name asc",
	)
	budgets = {
		b.project: b
		for b in frappe.get_all(
			"Project Budget",
			filters={"docstatus": 1},
			fields=[
				"project", "total_current_budget", "total_committed", "total_actual", "total_available",
				"total_forecast_final_cost",
			],
		)
	}
	rows = []
	for p in projects:
		budget = budgets.get(p.name) or frappe._dict()
		p.revised_contract = flt(p.muhick_contract_value) + flt(p.muhick_approved_variations)
		p.certified = flt(p.muhick_certified_to_date)
		p.percent_certified = p.certified / p.revised_contract * 100 if p.revised_contract else 0
		p.retention_balance = flt(p.muhick_retention_held) - flt(p.muhick_retention_released)
		p.current_budget = flt(budget.total_current_budget)
		p.committed = flt(budget.total_committed)
		p.actual = flt(budget.total_actual)
		p.available = flt(budget.total_available)
		p.forecast_final_cost = flt(budget.total_forecast_final_cost)
		p.forecast_margin = p.revised_contract - p.forecast_final_cost if budget else None
		rows.append(p)
	return columns, rows
