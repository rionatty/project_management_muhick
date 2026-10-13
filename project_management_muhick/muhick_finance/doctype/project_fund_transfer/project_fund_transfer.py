# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Money moved from one project's funds to another. Funds are held project by project, not in
one pool: when a project runs ahead of its own receipts it uses another project's money (often a
client advance) and refunds it later. Each transfer is approved and stays outstanding until it
is refunded, so the position of every project is known."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import draft_status


class ProjectFundTransfer(Document):
	def validate(self):
		if self.from_project == self.to_project:
			frappe.throw(_("Select two different projects."))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount."))
		self.outstanding_amount = flt(self.amount)
		self.status = draft_status(self)

	def before_submit(self):
		self.refunded_amount = 0
		self.outstanding_amount = flt(self.amount)
		self.status = "Outstanding"

	def before_update_after_submit(self):
		self.refunded_amount = sum(flt(r.amount) for r in self.refunds)
		if self.refunded_amount > flt(self.amount) + 0.005:
			frappe.throw(_("Refunds cannot be more than the amount transferred."))
		self.outstanding_amount = flt(self.amount) - self.refunded_amount
		if self.outstanding_amount <= 0.005:
			self.status = "Refunded"
		else:
			self.status = "Partly Refunded" if self.refunded_amount else "Outstanding"

	def on_cancel(self):
		if self.refunds:
			frappe.throw(_("Refunds have been recorded against this transfer; it cannot be cancelled."))
		self.db_set("status", "Cancelled")
