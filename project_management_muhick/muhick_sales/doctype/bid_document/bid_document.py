# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""One document going in with a bid (a licence, the books of accounts, the technical proposal, the
priced BOQ...), tracked on its own: who prepares it, by when, how far it is and its file. It is ready
only with its file, and a licence or certificate only if it is still valid on the submission
deadline. The bid's document checklist follows each change."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate

from project_management_muhick.overrides.crm import sync_checklist


class BidDocument(Document):
	def validate(self):
		bid = frappe.db.get_value(
			"Opportunity", self.opportunity, ["customer_name", "opportunity_owner", "muhick_submission_deadline"], as_dict=True
		)
		self.organisation = bid.customer_name
		self.part = frappe.get_cached_value("Bid Document Type", self.document_type, "part")
		if not self.prepared_by:
			self.prepared_by = bid.opportunity_owner or frappe.session.user
		deadline = getdate(bid.muhick_submission_deadline) if bid.muhick_submission_deadline else None
		if not self.due_date:
			self.due_date = deadline
		if self.status == "Ready":
			if not self.file:
				frappe.throw(_("Attach the file of {0} before marking it ready.").format(self.document_type))
			if self.valid_until and deadline and getdate(self.valid_until) < deadline:
				frappe.throw(
					_("{0} is valid until {1}, before the submission deadline of {2}. Renew it before marking it ready.").format(
						self.document_type, formatdate(self.valid_until), formatdate(deadline)
					)
				)

	def on_update(self):
		if self.flags.skip_checklist_sync:
			return
		before = self.get_doc_before_save()
		if before and before.opportunity != self.opportunity:
			sync_checklist(before.opportunity)
		sync_checklist(self.opportunity)

	def on_trash(self):
		# off the bid's checklist first, which links to it
		frappe.db.set_value(
			"Bid Checklist Item", {"bid_document": self.name}, {"bid_document": None, "status": "Not Created", "prepared_by": None}
		)

	def after_delete(self):
		sync_checklist(self.opportunity)
