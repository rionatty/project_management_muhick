# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Funds for a bid: the bid document, bank charges, site visit and similar costs. Prepared by the
Sales Engineer, approved by the Head of Sales and the General Manager. The weekly payment plan then
pays it to the person's account, and they account for it: see muhick_finance/cash_requisition.py."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_finance.cash_requisition import CashRequisition
from project_management_muhick.muhick_projects.utils import check_overdue_accountability, draft_status, leaving_draft, validate_dates
from project_management_muhick.overrides.crm import refresh_bid_status


class SalesRequisition(CashRequisition, Document):
	EXPENSE_SOURCE = ("Financial Requirement Type", "expense_type")

	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.requisition_date, self.required_by, _("Date"), _("Required By"))
		self.total_amount = sum(flt(row.amount) for row in self.items)
		if self.total_amount <= 0:
			frappe.throw(_("Enter the amount being requested."))
		self.set_recipient()
		self.status = draft_status(self)
		if self.docstatus == 0 and leaving_draft(self):
			self.check_pending_accountability()
			self.check_ready_to_send()

	def check_pending_accountability(self):
		check_overdue_accountability(self)

	def after_insert(self):
		# money asked for the bid: its preparation has started
		refresh_bid_status(self.opportunity)

	def before_submit(self):
		self.status = "Approved"

	def on_cancel(self):
		if flt(self.amount_issued):
			frappe.throw(_("Money has already been issued against this requisition; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	def after_money_moved(self):
		refresh_bid_status(self.opportunity)
