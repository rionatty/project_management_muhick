# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Cash requisition for a project (fuel, transport, site visits, mobilization, petty cash) and its
accountability.

Approval: Project Manager -> COO -> Finance -> General Manager, shortened by the approval
thresholds. An unbudgeted (exception) claim goes COO -> General Manager and must say why the
cost was missed in the budget.

The weekly payment plan then pays it to the person's account, and they account for it: see
muhick_finance/cash_requisition.py.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_finance.cash_requisition import CashRequisition
from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import check_overdue_accountability, draft_status, leaving_draft, set_amounts, validate_dates
from project_management_muhick.utils.approval import get_route


class ProjectRequisition(CashRequisition, Document):
	EXPENSE_SOURCE = ("Cost Code", "cost_code")

	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.requisition_date, self.required_by, _("Date"), _("Required By"))
		self.total_amount = set_amounts(self.items)
		if self.total_amount <= 0:
			frappe.throw(_("Enter the amount being requested."))
		self.set_recipient()
		self.set_route_and_budget()
		self.status = draft_status(self)
		if self.docstatus == 0 and leaving_draft(self):
			self.check_pending_accountability()
			self.check_ready_to_send()

	def set_route_and_budget(self):
		if self.is_unbudgeted:
			if not (self.unbudgeted_reason or "").strip():
				frappe.throw(_("Explain why this cost was missed in the approved budget."))
			self.approval_route = "Unbudgeted Exception"
			self.budget_status = "Not Budgeted"
			self.budget_remarks = _("Raised as an exception outside the approved budget.")
			return
		self.approval_route = get_route(self.doctype, self.total_amount)
		self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, self.amounts_by_cost_code())
		if self.priority == "Urgent" and not (self.priority_reason or "").strip():
			frappe.throw(_("Give the reason this requisition is urgent."))

	def amounts_by_cost_code(self) -> dict:
		amounts = defaultdict(float)
		for row in self.items:
			amounts[row.cost_code] += flt(row.amount)
		return amounts

	def check_pending_accountability(self):
		"""No new cash while an earlier advance is overdue for accountability."""
		check_overdue_accountability(self)

	def before_submit(self):
		if not self.is_unbudgeted:
			# checked again at final approval: other commitments may have been approved meanwhile
			self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, self.amounts_by_cost_code())
			budget_engine.enforce(self, "budget_action_on_requisition", self.budget_status, self.budget_remarks)
		self.status = "Approved"

	def on_submit(self):
		budget_engine.refresh_projects([self.project])

	def on_cancel(self):
		if flt(self.amount_issued):
			frappe.throw(_("Money has already been issued against this requisition; it cannot be cancelled."))
		self.db_set("status", "Cancelled")
		budget_engine.refresh_projects([self.project])

	def after_money_moved(self):
		budget_engine.refresh_projects([self.project])
