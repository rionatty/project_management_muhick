# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Funds for a bid: the bid document, bank charges, site visit and similar costs. Prepared by the
Sales Engineer, approved by the Head of Sales and the General Manager, then paid by Finance.
The engineer accounts for the money afterwards: an unspent balance is returned, an overspend is
reimbursed."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, now_datetime, nowdate

from project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan import settle_plan_line
from project_management_muhick.muhick_projects.utils import check_overdue_accountability, draft_status, leaving_draft, validate_dates
from project_management_muhick.overrides.crm import refresh_bid_status
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, notify, notify_roles, require_roles, setting

OPEN_ACCOUNTABILITY = ("Paid", "Accountability Submitted")


class SalesRequisition(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.requisition_date, self.required_by, _("Date"), _("Required By"))
		self.total_amount = sum(flt(row.amount) for row in self.items)
		if self.total_amount <= 0:
			frappe.throw(_("Enter the amount being requested."))
		self.status = draft_status(self)
		if self.docstatus == 0 and leaving_draft(self):
			self.check_pending_accountability()

	def check_pending_accountability(self):
		check_overdue_accountability(self)

	def after_insert(self):
		# money asked for the bid: its preparation has started
		refresh_bid_status(self.opportunity)

	def before_submit(self):
		self.status = "Approved"

	def before_update_after_submit(self):
		before = self.get_doc_before_save()
		changed = before and [e.amount for e in before.expenses] != [e.amount for e in self.expenses]
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
		settle_plan_line(self.doctype, self.name, amount_issued)
		refresh_bid_status(self.opportunity)
		notify([self.requested_by], _("{0} has been paid. Account for it by {1}.").format(self.name, self.accountability_due_date), doc=self)

	@frappe.whitelist()
	def submit_accountability(self):
		self._require_status("Paid")
		if not self.expenses:
			frappe.throw(_("Record the expenses incurred, with receipts, before submitting the accountability."))
		self.set_position()
		self.db_set(
			{
				"amount_spent": self.amount_spent,
				"balance_to_return": self.balance_to_return,
				"reimbursement_due": self.reimbursement_due,
				"status": "Accountability Submitted",
			}
		)
		notify_roles(FINANCE_ROLES, _("Accountability for {0} is ready to verify.").format(self.name), doc=self)

	@frappe.whitelist()
	def verify_accountability(self):
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
				"status": "Closed" if settled else "Accounted",
			}
		)

	@frappe.whitelist()
	def settle(self, amount: float, reference: str | None = None):
		"""Finance records the balance returned by the engineer, or the reimbursement paid to them."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accounted")
		amount = flt(amount)
		due = flt(self.balance_to_return) - flt(self.returned_amount) if flt(self.balance_to_return) else flt(self.reimbursement_due)
		if amount <= 0 or amount > due + 0.005:
			frappe.throw(_("The amount still to settle is {0}.").format(frappe.format_value(due, "Currency")))
		values = {"return_reference": reference}
		if flt(self.balance_to_return):
			values["returned_amount"] = flt(self.returned_amount) + amount
			values["status"] = "Closed" if values["returned_amount"] >= flt(self.balance_to_return) - 0.005 else "Accounted"
		else:
			values["status"] = "Closed"
		self.db_set(values)
