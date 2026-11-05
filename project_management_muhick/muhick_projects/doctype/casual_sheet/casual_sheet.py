# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Casual sheet: the casual workers actually engaged in a period and what they are owed. Casuals
are paid in arrears, so the sheet is prepared after the work, checked against the approved
labour schedules, and approved Project Manager -> COO -> Finance Manager. It goes straight to
Finance and never through Procurement. An approved sheet is a commitment on the budget."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan import settle_plan_line
from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import draft_status, leaving_draft, validate_dates
from project_management_muhick.utils.common import FINANCE_ROLES, notify, require_roles


class CasualSheet(Document):
	def validate(self):
		validate_dates(self.period_from, self.period_to, _("Period From"), _("Period To"))
		workers = set()
		self.total_man_days = self.total_amount = 0.0
		for row in self.lines:
			if flt(row.days_worked) <= 0:
				frappe.throw(_("Casual Sheet row {0}: enter the days worked.").format(row.idx))
			row.amount = flt(row.days_worked) * flt(row.daily_rate)
			workers.add(((row.worker_name or "").strip().lower(), row.id_number or ""))
			self.total_man_days += flt(row.days_worked)
			self.total_amount += row.amount
		self.total_workers = len(workers)
		self.set_schedule_variance()
		self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, {self.cost_code: self.total_amount})
		self.status = draft_status(self)
		if self.docstatus == 0 and leaving_draft(self):
			self.expense_lines()

	def set_schedule_variance(self):
		scheduled = frappe.get_all(
			"Labour Schedule",
			filters={"project": self.project, "docstatus": 1, "week_start": ("between", [self.period_from, self.period_to])},
			pluck="total_amount",
		)
		self.scheduled_amount = sum(flt(a) for a in scheduled)
		self.variance = flt(self.total_amount) - flt(self.scheduled_amount)
		# variances from the scheduled numbers or costs need an explanation before funds are released
		if self.variance > 0.5 and leaving_draft(self) and not (self.variance_explanation or "").strip():
			frappe.throw(
				_("This sheet is {0} above the approved labour schedule for the period. Explain the variance.").format(
					frappe.format_value(self.variance, "Currency")
				)
			)

	def before_submit(self):
		# checked again at final approval: other commitments may have been approved meanwhile
		self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, {self.cost_code: self.total_amount})
		budget_engine.enforce(self, "budget_action_on_requisition", self.budget_status, self.budget_remarks)
		self.status = "Approved"

	def on_submit(self):
		budget_engine.refresh_projects([self.project])

	def on_cancel(self):
		if self.status == "Paid":
			frappe.throw(_("This casual sheet has been paid and cannot be cancelled."))
		self.db_set("status", "Cancelled")
		budget_engine.refresh_projects([self.project])

	def expense_lines(self) -> list:
		"""What its payment posts: the wages, to its expense account. A casual sheet is its own accounting."""
		self.expense_account = self.expense_account or frappe.db.get_value("Cost Code", self.cost_code, "expense_account")
		if not self.expense_account:
			frappe.throw(_("Choose the Expense Account on {0}.").format(self.name))
		return [(self.expense_account, flt(self.total_amount), _("Casual labour, {0} to {1}").format(self.period_from, self.period_to))]

	def mark_paid(self, amount: float, paid_on: str | None = None, payment_reference: str | None = None):
		"""The plan's journal entry is submitted: the wages are paid, in full or towards them."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Only an approved, unpaid casual sheet can be marked as paid."))
		paid = flt(self.paid_amount) + flt(amount)
		self.db_set(
			{
				"paid_amount": paid,
				"status": "Paid" if paid >= flt(self.total_amount) - 0.005 else "Approved",
				"paid_on": paid_on or nowdate(),
				"payment_reference": payment_reference,
			}
		)
		settle_plan_line(self.doctype, self.name, flt(amount))
		budget_engine.refresh_projects([self.project])
		notify([self.owner], _("Casual sheet {0} has been paid.").format(self.name), doc=self)

	def reverse_funds(self, reference=None):
		"""The plan's journal entry is cancelled: what it paid is owed again."""
		require_roles(*FINANCE_ROLES)
		paid = flt(self.paid_amount) - flt(frappe.db.get_value("Journal Entry", reference, "total_debit"))
		self.db_set({"paid_amount": max(paid, 0), "status": "Approved", "paid_on": None, "payment_reference": None})
		budget_engine.refresh_projects([self.project])
