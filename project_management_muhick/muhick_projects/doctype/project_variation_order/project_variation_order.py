# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Client variation: a change in quantity, value or scope after award.
Approval changes the revised contract value, makes the new lines claimable and
raises a Project Budget Revision for the cost side, so the Original Budget is never overwritten."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import leaving_draft, set_amounts
from project_management_muhick.overrides import project as project_api


class ProjectVariationOrder(Document):
	def validate(self):
		self.total_amount = set_amounts(self.items)
		self.total_estimated_cost = 0
		for row in self.items:
			if flt(row.estimated_cost) and not row.cost_code:
				frappe.throw(_("Variation Items row {0}: select the cost code that takes the cost impact.").format(row.idx))
			self.total_estimated_cost += flt(row.estimated_cost)
		if leaving_draft(self) and not self.client_approval:
			frappe.throw(_("Attach the client's approval of this variation before sending it for approval."))

	def on_submit(self):
		project_api.update_position(self.project)
		self.make_budget_revision()
		budget_engine.refresh_projects([self.project])

	def make_budget_revision(self):
		by_cost_code = defaultdict(float)
		for row in self.items:
			if flt(row.estimated_cost):
				by_cost_code[row.cost_code] += flt(row.estimated_cost)
		by_cost_code = {k: v for k, v in by_cost_code.items() if abs(v) > 0.005}
		if not by_cost_code or not budget_engine.get_approved_budget(self.project):
			return
		revision = frappe.new_doc("Project Budget Revision")
		revision.update(
			{
				"project": self.project,
				"revision_type": "Client Variation",
				"variation_order": self.name,
				"reason": _("Variation {0}: {1}").format(self.name, self.title),
			}
		)
		for cost_code, change in by_cost_code.items():
			revision.append(
				"lines", {"cost_code": cost_code, "change_amount": change, "justification": self.description, "description": self.title}
			)
		revision.insert(ignore_permissions=True)
		self.db_set("budget_revision", revision.name)
		frappe.msgprint(
			_("Budget revision {0} was drafted for the cost of this variation. It needs approval to change the budget.").format(revision.name),
			indicator="blue",
		)

	def on_cancel(self):
		rows = tuple(r.name for r in self.items) or ("",)
		claimed = frappe.db.sql(
			"""
			select c.name from `tabProject Claim Item` ci inner join `tabProject Claim` c on c.name = ci.parent
			where c.docstatus = 1 and ci.source_row in %(rows)s limit 1
			""",
			{"rows": rows},
		)
		if claimed:
			frappe.throw(_("Claim {0} includes this variation, so it cannot be cancelled.").format(claimed[0][0]))
		if self.budget_revision:
			docstatus = frappe.db.get_value("Project Budget Revision", self.budget_revision, "docstatus")
			if docstatus == 1:
				frappe.throw(_("Cancel budget revision {0} first.").format(self.budget_revision))
			if docstatus == 0:
				frappe.delete_doc("Project Budget Revision", self.budget_revision, ignore_permissions=True)
			self.db_set("budget_revision", None)
		project_api.update_position(self.project)
		budget_engine.refresh_projects([self.project])
