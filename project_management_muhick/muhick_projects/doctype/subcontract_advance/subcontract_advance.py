# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The requisition for a subcontract's advance. Operations asks for what the agreement's payment terms allow, Finance and
the General Manager sign it off, and it goes on the weekly payment plan. Once paid it is on the subcontractor's account,
and each Service Receipt Note recovers its share."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.doctype.subcontract_agreement.subcontract_agreement import update_position
from project_management_muhick.muhick_projects.utils import draft_status

FROM_AGREEMENT = ("supplier", "supplier_name", "project", "company", "cost_code")


class SubcontractAdvance(Document):
	def validate(self):
		agreement = frappe.db.get_value(
			"Subcontract Agreement", self.subcontract_agreement, ["docstatus", "status", *FROM_AGREEMENT], as_dict=True
		)
		if not agreement or agreement.docstatus != 1 or agreement.status != "Active":
			frappe.throw(_("Agreement {0} is not active.").format(self.subcontract_agreement))
		for field in FROM_AGREEMENT:
			self.set(field, agreement.get(field))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount."))
		left = get_advance_left(self.subcontract_agreement, self.name)
		if flt(self.amount) > left + 0.5:
			frappe.throw(_("The agreement's payment terms leave {0} of its advance to request.").format(frappe.format_value(left, "Currency")))
		self.status = draft_status(self)

	def before_submit(self):
		self.status = "Approved"

	def on_cancel(self):
		if flt(self.paid_amount):
			frappe.throw(_("This advance has been paid. Cancel its payment first."))
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def get_advance_left(agreement: str, advance: str | None = None) -> float:
	"""What an agreement's payment terms still allow to be requested as its advance, leaving out the request given."""
	terms = frappe.db.get_value("Subcontract Agreement", agreement, "advance_amount")
	requested = frappe.get_all(
		"Subcontract Advance",
		filters={"subcontract_agreement": agreement, "docstatus": ("<", 2), "status": ("!=", "Rejected"), "name": ("!=", advance or "")},
		pluck="amount",
	)
	return flt(terms) - sum(flt(amount) for amount in requested)


def carry_payment(advance):
	"""A payment of an advance submitted or cancelled: the advance, and its agreement's position, follow."""
	entries = frappe.get_all(
		"Payment Entry",
		filters={"muhick_subcontract_advance": advance, "docstatus": 1},
		fields=["name", "base_paid_amount", "posting_date"],
		order_by="posting_date asc",
	)
	paid = sum(flt(entry.base_paid_amount) for entry in entries)
	amount, agreement = frappe.db.get_value("Subcontract Advance", advance, ["amount", "subcontract_agreement"])
	frappe.db.set_value(
		"Subcontract Advance",
		advance,
		{
			"paid_amount": paid,
			"payment_entry": entries[-1].name if entries else None,
			"paid_on": entries[-1].posting_date if entries else None,
			"status": "Paid" if paid >= flt(amount) - 0.5 else "Approved",
		},
		update_modified=False,
	)
	update_position(agreement)
