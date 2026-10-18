# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Project budget, built and controlled inside the ERP by cost code.

Each line is an item from the Item master, placed in a phase (a group task of the project) and,
optionally, one of its activities. The lines can be taken from the items of the approved
activity plan; the cost code is proposed from the item.

The approved figures are the Original Budget and never change. Later changes arrive only
through approved Project Budget Revisions, so Original Budget, Approved Variations, Current
Budget and Forecast Final Cost are always kept separately.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import check_phase, set_amounts

KEEP = ("opening_actual", "opening_paid", "etc_is_manual", "estimate_to_complete")


class ProjectBudget(Document):
	def validate(self):
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		self.check_single_budget()
		self.validate_phases()
		set_amounts(self.lines)
		self.build_cost_code_summary()
		self.set_totals()

	def check_single_budget(self):
		other = frappe.db.get_value(
			"Project Budget",
			{"project": self.project, "docstatus": ("<", 2), "name": ("!=", self.name or "")},
			["name", "docstatus"],
			as_dict=True,
		)
		if not other:
			return
		if other.docstatus == 1:
			frappe.throw(
				_("Project {0} already has an approved budget ({1}). Change it through a Project Budget Revision.").format(
					self.project, other.name
				)
			)
		frappe.throw(_("Project {0} already has a draft budget: {1}.").format(self.project, other.name))

	def validate_phases(self):
		for line in self.lines:
			if line.activity:
				parent = frappe.db.get_value("Task", line.activity, "parent_task")
				if line.phase and parent != line.phase:
					frappe.throw(_("Budget Lines row {0}: {1} is not an activity of phase {2}.").format(line.idx, line.activity, line.phase))
				line.phase = line.phase or parent
			if line.phase:
				check_phase(self.project, line.phase, _("Budget Lines row {0}").format(line.idx))

	def build_cost_code_summary(self):
		"""One control row per cost code, rebuilt from the lines while the budget is a draft."""
		kept = {row.cost_code: {f: row.get(f) for f in KEEP} for row in self.cost_codes}
		totals, sections = defaultdict(float), {}
		for line in self.lines:
			disabled, section = frappe.get_cached_value("Cost Code", line.cost_code, ["disabled", "budget_section"])
			if disabled:
				frappe.throw(_("Budget Lines row {0}: cost code {1} is disabled.").format(line.idx, line.cost_code))
			line.budget_section = section
			totals[line.cost_code] += flt(line.amount)
			sections[line.cost_code] = section
		self.set("cost_codes", [])
		order = {"Materials": 0, "Works": 1, "Administrative": 2}
		for cost_code in sorted(totals, key=lambda c: (order.get(sections[c], 9), c)):
			row = {
				"cost_code": cost_code,
				"budget_section": sections[cost_code],
				"original_budget": totals[cost_code],
				"approved_variations": 0,
				"current_budget": totals[cost_code],
				"available": totals[cost_code],
				"forecast_final_cost": totals[cost_code],
			}
			row.update(kept.get(cost_code, {}))
			self.append("cost_codes", row)

	def set_totals(self):
		self.total_original_budget = sum(flt(r.original_budget) for r in self.cost_codes)
		self.total_approved_variations = 0
		self.total_current_budget = self.total_original_budget
		self.total_available = self.total_current_budget
		self.total_forecast_final_cost = self.total_current_budget
		contract = frappe.db.get_value(
			"Project", self.project, ["muhick_contract_value", "muhick_approved_variations"], as_dict=True
		)
		self.contract_value = flt(contract.muhick_contract_value) + flt(contract.muhick_approved_variations) if contract else 0
		self.planned_margin = flt(self.contract_value) - flt(self.total_current_budget)
		self.forecast_margin = self.planned_margin

	def on_submit(self):
		frappe.db.set_value(
			"Project", self.project, {"muhick_budget": self.name, "estimated_costing": self.total_current_budget}
		)
		budget_engine.update_budget(self.project)

	def on_update_after_submit(self):
		# the Project Manager keeps the Estimate to Complete current; the forecast follows it
		budget_engine.update_budget(self.project)

	def on_cancel(self):
		revision = frappe.db.get_value("Project Budget Revision", {"project_budget": self.name, "docstatus": 1}, "name")
		if revision:
			frappe.throw(
				_("Budget revision {0} has been approved against this budget. Cancel the revision first.").format(revision)
			)
		if frappe.db.get_value("Project", self.project, "muhick_budget") == self.name:
			frappe.db.set_value("Project", self.project, "muhick_budget", None)


@frappe.whitelist()
def get_plan_items(project: str) -> list:
	"""Budget lines for the items of the project's approved activity plan, phase by phase.
	The rate is the item's last purchase rate (or valuation rate) and can be changed."""
	frappe.has_permission("Project Budget", "create", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	plan_name = frappe.db.get_value("Project Activity Plan", {"project": project, "docstatus": 1, "is_current": 1}, "name")
	if not plan_name:
		frappe.throw(_("Approve the activity plan of project {0} first; its items are the starting point of the budget.").format(project))
	plan = frappe.get_doc("Project Activity Plan", plan_name)
	phases = {r.phase_name: r.phase for r in plan.phases}
	rows = []
	for item in plan.items:
		info = frappe.get_cached_value(
			"Item", item.item_code, ["item_name", "stock_uom", "muhick_cost_code", "last_purchase_rate", "valuation_rate"], as_dict=True
		)
		rows.append(
			{
				"phase": phases.get(item.phase_name),
				"item_code": item.item_code,
				"description": info.item_name,
				"uom": item.uom or info.stock_uom,
				"qty": item.qty,
				"rate": flt(info.last_purchase_rate) or flt(info.valuation_rate),
				"cost_code": info.muhick_cost_code,
				"required_by_date": item.required_by,
			}
		)
	return rows
