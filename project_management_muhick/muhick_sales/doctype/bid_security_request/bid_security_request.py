# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A request for a bid security. The Sales Executive raises it from the bid (the opportunity); the
Finance Manager and the General Manager are told, and the Finance Manager approves it or rejects it
with the reason: a rejected request is amended and sent again, or left closed while the bid goes on.
Once it is approved, Finance issues the funds needed to obtain the security, and records the security
itself when the bank or insurer has issued it."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_projects.utils import draft_status, validate_dates
from project_management_muhick.utils.common import FINANCE_ROLES, notify, require_roles


class BidSecurityRequest(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.request_date, self.required_by, _("Date"), _("Required By"))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount of the bid security."))
		self.status = draft_status(self)
		if self.has_value_changed("workflow_state") and self.workflow_state == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Give the reason for the rejection, and say whether the request can be amended and sent again."))

	def before_submit(self):
		self.status = "Approved"

	def on_cancel(self):
		if flt(self.amount_issued):
			frappe.throw(_("Funds have already been issued for this request; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def record_funds_issued(self, amount_issued: float, issued_on: str | None = None, payment_reference: str | None = None):
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Funds are issued once the request is approved."))
		if flt(amount_issued) <= 0:
			frappe.throw(_("Enter the amount issued."))
		self.db_set(
			{
				"amount_issued": flt(amount_issued),
				"issued_on": issued_on or nowdate(),
				"payment_reference": payment_reference,
				"status": "Funds Issued",
			}
		)
		notify([self.requested_by], _("Funds for bid security request {0} have been issued.").format(self.name), doc=self)


@frappe.whitelist()
def make_bank_instrument(source_name: str):
	"""The bid security as issued by the bank or insurer, recorded by Finance."""
	request = frappe.get_doc("Bid Security Request", source_name)
	request.check_permission("read")
	doc = frappe.new_doc("Bank Instrument")
	doc.update(
		{
			"title": _("Bid security: {0}").format(request.organisation),
			"instrument_type": "Bid Security",
			"opportunity": request.opportunity,
			"company": request.company,
			"beneficiary": request.beneficiary,
			"amount": request.amount,
		}
	)
	return doc
