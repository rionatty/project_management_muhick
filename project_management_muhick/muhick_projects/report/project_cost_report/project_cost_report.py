# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Budget position: Original Budget, Approved Variations, Current Budget, Committed, Actual,
Paid, Available and Forecast Final Cost. By cost code for one project, or one line per project."""

import frappe
from frappe import _

from project_management_muhick.muhick_projects import budget_engine

MONEY = [
	("original_budget", "Original Budget"),
	("approved_variations", "Approved Variations"),
	("current_budget", "Current Budget"),
	("committed", "Committed"),
	("actual", "Actual Cost"),
	("paid", "Paid"),
	("available", "Available"),
	("estimate_to_complete", "Estimate to Complete"),
	("forecast_final_cost", "Forecast Final Cost"),
	("forecast_variance", "Forecast Variance"),
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return by_cost_code(filters.project) if filters.project else by_project(filters)


def money_columns(skip=()):
	return [
		{"fieldname": f, "label": _(label), "fieldtype": "Currency", "width": 140}
		for f, label in MONEY
		if f not in skip
	]


def by_cost_code(project):
	columns = [
		{"fieldname": "cost_code", "label": _("Cost Code"), "fieldtype": "Link", "options": "Cost Code", "width": 110},
		{"fieldname": "cost_code_name", "label": _("Description"), "fieldtype": "Data", "width": 220},
		{"fieldname": "budget_section", "label": _("Budget Section"), "fieldtype": "Data", "width": 110},
		*money_columns(),
	]
	budget = budget_engine.update_budget(project)
	if not budget:
		frappe.msgprint(_("Project {0} has no approved budget.").format(project))
		return columns, []
	rows = frappe.get_all(
		"Project Budget Cost Code",
		filters={"parent": budget},
		fields=["cost_code", "budget_section", *[f for f, _label in MONEY]],
		order_by="idx asc",
	)
	names = dict(frappe.get_all("Cost Code", fields=["name", "cost_code_name"], as_list=True))
	for row in rows:
		row.cost_code_name = names.get(row.cost_code)
	unbudgeted = frappe.db.get_value("Project Budget", budget, "unbudgeted_committed")
	if unbudgeted:
		rows.append(
			frappe._dict(
				cost_code_name=_("Committed outside the budgeted cost codes"),
				committed=unbudgeted,
				available=-unbudgeted,
				forecast_final_cost=unbudgeted,
				forecast_variance=-unbudgeted,
			)
		)
	return columns, rows


def by_project(filters):
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 130},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "contract_value", "label": _("Revised Contract Value"), "fieldtype": "Currency", "width": 150},
		*money_columns(skip=("estimate_to_complete", "forecast_variance")),
		{"fieldname": "forecast_margin", "label": _("Forecast Margin"), "fieldtype": "Currency", "width": 140},
	]
	conditions = {"docstatus": 1}
	if filters.company:
		conditions["company"] = filters.company
	rows = frappe.get_all(
		"Project Budget",
		filters=conditions,
		fields=[
			"project", "project_name", "contract_value",
			"total_original_budget as original_budget", "total_approved_variations as approved_variations",
			"total_current_budget as current_budget", "total_committed as committed", "total_actual as actual",
			"total_paid as paid", "total_available as available",
			"total_forecast_final_cost as forecast_final_cost", "forecast_margin",
		],
		order_by="project asc",
	)
	return columns, rows
