# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Cash requisition for a project (fuel, transport, site visits, mobilization, petty cash) and its
accountability.

Approval: Project Manager -> COO -> Finance -> General Manager, shortened by the approval
thresholds. An unbudgeted (exception) claim goes COO -> General Manager and must say why the
cost was missed in the budget.

Accountability: if more was issued than spent, the requester
returns the balance; if more was spent than issued, the company reimburses the requester.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, now_datetime, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import check_overdue_accountability, draft_status, leaving_draft, set_amounts, validate_dates
from project_management_muhick.utils import calc
from project_management_muhick.utils.approval import get_route
from project_management_muhick.utils.common import FINANCE_ROLES, GM, notify, notify_roles, require_roles, setting

OPEN_ACCOUNTABILITY = ("Paid", "Accountability Submitted")


class ProjectRequisition(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.requisition_date, self.required_by, _("Date"), _("Required By"))
		self.total_amount = set_amounts(self.items)
		if self.total_amount <= 0:
			frappe.throw(_("Enter the amount being requested."))
		self.set_route_and_budget()
		self.status = draft_status(self)
		if self.docstatus == 0 and leaving_draft(self):
			self.check_pending_accountability()

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

	def before_update_after_submit(self):
		"""The requester records the expenses on the approved requisition."""
		before = self.get_doc_before_save()
		changed = before and [(e.amount, e.cost_code) for e in before.expenses] != [(e.amount, e.cost_code) for e in self.expenses]
		if changed and self.status not in OPEN_ACCOUNTABILITY:
			frappe.throw(_("Expenses can only be recorded after the money is issued and before the accountability is verified."))
		self.set_position()

	def set_position(self):
		self.amount_spent = sum(flt(e.amount) for e in self.expenses)
		position = calc.accountability_position(self.amount_issued, self.amount_spent, self.returned_amount)
		self.balance_to_return = position["balance_to_return"]
		self.reimbursement_due = position["reimbursement_due"]

	def on_cancel(self):
		if flt(self.amount_issued):
			frappe.throw(_("Money has already been issued against this requisition; it cannot be cancelled."))
		self.db_set("status", "Cancelled")
		budget_engine.refresh_projects([self.project])

	# ------------------------------------------------------------------ after approval
	def _require_status(self, *allowed):
		if self.docstatus != 1 or self.status not in allowed:
			frappe.throw(_("This is not possible while the requisition is {0}.").format(_(self.status)))

	@frappe.whitelist()
	def mark_paid(
		self,
		amount_issued: float,
		issued_on: str | None = None,
		payment_reference: str | None = None,
		accountability_due_date: str | None = None,
	):
		"""Finance records the money issued (outgoing payment process)."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Approved")
		amount_issued = flt(amount_issued)
		if amount_issued <= 0 or amount_issued > flt(self.total_amount) + 0.005:
			frappe.throw(_("The amount issued must be more than zero and not more than the approved amount."))
		issued_on = issued_on or nowdate()
		due = accountability_due_date or add_days(issued_on, setting("accountability_due_days", 7))
		validate_dates(issued_on, due, _("Issued On"), _("Account By"))
		self.db_set(
			{
				"amount_issued": amount_issued,
				"issued_on": issued_on,
				"payment_reference": payment_reference,
				"accountability_due_date": due,
				"status": "Paid",
			}
		)
		budget_engine.refresh_projects([self.project])
		notify([self.requested_by], _("{0} has been paid. Account for it by {1}.").format(self.name, self.accountability_due_date), doc=self)

	@frappe.whitelist()
	def submit_accountability(self):
		"""The requester hands in the accountability with receipts."""
		self._require_status("Paid")
		if not self.expenses:
			frappe.throw(_("Record the expenses incurred, with receipts, before submitting the accountability."))
		self.set_position()
		self.db_set(
			{
				"amount_spent": self.amount_spent,
				"balance_to_return": self.balance_to_return,
				"reimbursement_due": self.reimbursement_due,
				"accountability_submitted_on": now_datetime(),
				"status": "Accountability Submitted",
			}
		)
		notify_roles(FINANCE_ROLES, _("Accountability for {0} is ready to verify.").format(self.name), doc=self)

	@frappe.whitelist()
	def verify_accountability(self):
		"""Finance verifies the accountability against the supporting documents."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accountability Submitted")
		self.set_position()
		settled = not self.balance_to_return and not self.reimbursement_due
		self.db_set(
			{
				"amount_spent": self.amount_spent,
				"balance_to_return": self.balance_to_return,
				"reimbursement_due": self.reimbursement_due,
				"verified_by": frappe.session.user,
				"verified_on": now_datetime(),
				"status": "Closed" if settled else "Accounted",
			}
		)
		budget_engine.refresh_projects([self.project])
		if self.balance_to_return:
			notify([self.requested_by], _("{0}: return the unspent balance of {1} to Finance.").format(
				self.name, frappe.format_value(self.balance_to_return, "Currency")), doc=self)
		elif self.reimbursement_due:
			notify_roles(GM, _("{0}: a reimbursement of {1} needs your approval.").format(
				self.name, frappe.format_value(self.reimbursement_due, "Currency")), doc=self)

	@frappe.whitelist()
	def record_return(self, amount: float, reference: str | None = None):
		"""Finance receives the unspent balance back from the requester."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accounted")
		outstanding = flt(self.balance_to_return) - flt(self.returned_amount)
		amount = flt(amount)
		if amount <= 0 or amount > outstanding + 0.005:
			frappe.throw(_("The balance still to be returned is {0}.").format(frappe.format_value(outstanding, "Currency")))
		returned = flt(self.returned_amount) + amount
		self.db_set(
			{
				"returned_amount": returned,
				"return_reference": reference,
				"status": "Closed" if returned >= flt(self.balance_to_return) - 0.005 else "Accounted",
			}
		)

	@frappe.whitelist()
	def approve_reimbursement(self):
		"""The General Manager approves refunding the requester for spend above the advance."""
		require_roles(GM)
		self._require_status("Accounted")
		if not flt(self.reimbursement_due):
			frappe.throw(_("No reimbursement is due on this requisition."))
		self.db_set("reimbursement_approved_by", frappe.session.user)
		notify_roles(FINANCE_ROLES, _("Reimbursement on {0} is approved. Pay the requester.").format(self.name), doc=self)

	@frappe.whitelist()
	def record_reimbursement(self, reference: str | None = None):
		"""Finance pays the approved reimbursement, which closes the requisition."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accounted")
		if not self.reimbursement_approved_by:
			frappe.throw(_("The General Manager has not approved this reimbursement yet."))
		self.db_set({"return_reference": reference, "status": "Closed"})
