# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Expense claim: someone spent their own money for the company and is refunded against
receipts. A project expense is approved by the COO and then the General Manager; an
administration expense by the General Manager. An emergency site purchase (for example a burst
pipe after hours) is a fast track: one named approver, then the refund.

Finance refunds the claimant with a journal entry that debits the expense accounts and credits
cash or bank."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import draft_status
from project_management_muhick.utils.common import FINANCE_ROLES, require_roles


class ReimbursementClaim(Document):
	def validate(self):
		if self.claim_type == "Emergency Site Purchase" and not (self.emergency_reason or "").strip():
			frappe.throw(_("Describe the emergency and why the purchase could not wait."))
		self.total_amount = 0
		amounts = defaultdict(float)
		for row in self.expenses:
			if flt(row.amount) <= 0:
				frappe.throw(_("Expenses row {0}: enter the amount.").format(row.idx))
			if self.project and not row.cost_code:
				frappe.throw(_("Expenses row {0}: select the cost code for this project expense.").format(row.idx))
			self.total_amount += flt(row.amount)
			amounts[row.cost_code] += flt(row.amount)
		if self.project:
			self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, amounts)
		else:
			self.budget_status, self.budget_remarks = "Not Applicable", ""
		self.status = draft_status(self)

	def before_submit(self):
		self.status = "Approved"

	def on_submit(self):
		budget_engine.refresh_projects([self.project])

	def on_cancel(self):
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			frappe.throw(_("Cancel journal entry {0} first.").format(self.journal_entry))
		self.db_set("status", "Cancelled")
		budget_engine.refresh_projects([self.project])

	@frappe.whitelist()
	def make_journal_entry(self, paid_from_account: str, posting_date: str | None = None):
		"""The refund: debit the expense accounts, credit cash or bank. Saved as a draft."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Only an approved, unpaid claim can be refunded."))
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") != 2:
			return self.journal_entry
		default_account, cost_center = frappe.get_cached_value("Company", self.company, ["default_expense_account", "cost_center"])
		entry = frappe.new_doc("Journal Entry")
		entry.update(
			{
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": posting_date or nowdate(),
				"user_remark": _("Refund of expense claim {0}: {1} ({2})").format(self.name, self.purpose, self.claimant_name),
				"muhick_reimbursement_claim": self.name,
			}
		)
		for row in self.expenses:
			account = row.expense_account or (
				frappe.get_cached_value("Cost Code", row.cost_code, "expense_account") if row.cost_code else None
			) or default_account
			if not account:
				frappe.throw(_("Expenses row {0}: no expense account. Set one on the row, the cost code or the company.").format(row.idx))
			entry.append(
				"accounts",
				{
					"account": account,
					"debit_in_account_currency": flt(row.amount),
					"project": self.project,
					"cost_center": cost_center,
					"user_remark": row.description,
				},
			)
		entry.append("accounts", {"account": paid_from_account, "credit_in_account_currency": flt(self.total_amount)})
		entry.insert()
		self.db_set({"journal_entry": entry.name, "paid_from_account": paid_from_account})
		return entry.name


def on_refund(entry, cancelled=False):
	"""Journal Entry submitted or cancelled: the claim becomes Paid, or goes back to Approved."""
	claim = entry.get("muhick_reimbursement_claim")
	if not claim or not frappe.db.exists("Reimbursement Claim", claim):
		return
	if cancelled:
		values = {"status": "Approved", "paid_on": None}
	else:
		values = {"status": "Paid", "paid_on": entry.posting_date, "journal_entry": entry.name}
	frappe.db.set_value("Reimbursement Claim", claim, values)
	budget_engine.refresh_projects([frappe.db.get_value("Reimbursement Claim", claim, "project")])
