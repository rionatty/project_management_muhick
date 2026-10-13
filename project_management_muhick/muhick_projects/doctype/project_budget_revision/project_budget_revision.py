# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A controlled change to an approved budget. Printed as the Project Cost Control Sheet when
sourced prices or quantities differ from the budget; also used for client variations and for
moving budget between cost codes. The Original Budget is never overwritten."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine


class ProjectBudgetRevision(Document):
	def validate(self):
		budget = budget_engine.get_approved_budget(self.project)
		if not budget:
			frappe.throw(_("Project {0} has no approved budget to revise.").format(self.project))
		self.project_budget = budget
		rows = budget_engine.get_budget_rows(budget)
		position = budget_engine.get_position(self.project)
		seen = set()
		self.total_increase = self.total_decrease = 0
		for line in self.lines:
			if line.cost_code in seen:
				frappe.throw(_("Revision Lines row {0}: cost code {1} appears twice.").format(line.idx, line.cost_code))
			seen.add(line.cost_code)
			if not flt(line.change_amount):
				frappe.throw(_("Revision Lines row {0}: enter the change amount.").format(line.idx))
			row = rows.get(line.cost_code)
			line.current_budget = flt(row.current_budget) if row else 0
			line.committed = (flt(row.opening_actual) if row else 0) + position.get(line.cost_code, {}).get("committed", 0)
			line.revised_budget = line.current_budget + flt(line.change_amount)
			if line.revised_budget < flt(line.committed) - 0.005:
				frappe.throw(
					_("Revision Lines row {0}: {1} cannot be reduced to {2}; {3} is already committed.").format(
						line.idx,
						line.cost_code,
						frappe.format_value(line.revised_budget, "Currency"),
						frappe.format_value(line.committed, "Currency"),
					)
				)
			if flt(line.change_amount) > 0:
				self.total_increase += flt(line.change_amount)
			else:
				self.total_decrease += -flt(line.change_amount)
		self.net_change = self.total_increase - self.total_decrease
		self.budget_before = sum(flt(r.current_budget) for r in rows.values())
		self.budget_after = self.budget_before + self.net_change
		if self.revision_type == "Reallocation" and abs(self.net_change) > 0.005:
			frappe.throw(_("A reallocation moves budget between cost codes and must net to zero."))
		if self.revision_type == "Client Variation" and not self.variation_order:
			frappe.throw(_("Select the Variation Order this budget change comes from."))

	def on_submit(self):
		self.apply(1)

	def on_cancel(self):
		self.apply(-1)

	def apply(self, sign):
		rows = budget_engine.get_budget_rows(self.project_budget)
		next_idx = len(rows) + 1
		for line in self.lines:
			change = sign * flt(line.change_amount)
			row = rows.get(line.cost_code)
			if row:
				frappe.db.set_value(
					"Project Budget Cost Code",
					row.name,
					{
						"approved_variations": flt(row.approved_variations) + change,
						"current_budget": flt(row.current_budget) + change,
					},
					update_modified=False,
				)
				continue
			# a cost code that was not in the original budget: its original stays zero
			child = frappe.new_doc("Project Budget Cost Code")
			child.update(
				{
					"parent": self.project_budget,
					"parenttype": "Project Budget",
					"parentfield": "cost_codes",
					"idx": next_idx,
					"docstatus": 1,
					"cost_code": line.cost_code,
					"budget_section": frappe.get_cached_value("Cost Code", line.cost_code, "budget_section"),
					"original_budget": 0,
					"approved_variations": change,
					"current_budget": change,
				}
			)
			child.db_insert()
			next_idx += 1
		budget_engine.update_budget(self.project)
