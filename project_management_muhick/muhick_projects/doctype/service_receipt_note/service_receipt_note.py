# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Service Receipt Note: the Project Manager certifies subcontracted work. It is the "goods received note" for services: Finance can only raise the
subcontractor's invoice against a submitted note, and the note can only be submitted with the
signed receipt and the subcontractor's milestone completion certificate. A final certificate
also needs Operations to confirm the subcontractor met its obligations."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.doctype.subcontract_agreement.subcontract_agreement import update_position
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, notify_roles, require_roles, setting

AGREEMENT_FIELDS = ["contract_amount", "advance_percent", "advance_amount", "advance_recovered", "retention_percent", "status", "docstatus"]


class ServiceReceiptNote(Document):
	def validate(self):
		agreement = frappe.db.get_value("Subcontract Agreement", self.subcontract_agreement, AGREEMENT_FIELDS, as_dict=True)
		if agreement.docstatus != 1 or agreement.status != "Active":
			frappe.throw(_("Agreement {0} is not active.").format(self.subcontract_agreement))
		if not self.items:
			self.load_items()
		self.retention_percent = agreement.retention_percent
		self.gross_amount = 0
		for row in self.items:
			row.previous_certified = self.previously_certified(row.agreement_row)
			row.cumulative = flt(row.previous_certified) + flt(row.this_certificate)
			if flt(row.this_certificate) < 0:
				frappe.throw(_("Certified Work row {0}: the amount cannot be negative.").format(row.idx))
			if flt(row.contract_amount) and row.cumulative > flt(row.contract_amount) + 0.5:
				frappe.throw(
					_("Certified Work row {0}: {1} certified to date is more than the {2} agreed for this milestone.").format(
						row.idx,
						frappe.format_value(row.cumulative, "Currency"),
						frappe.format_value(row.contract_amount, "Currency"),
					)
				)
			self.gross_amount += flt(row.this_certificate)
		if self.gross_amount <= 0:
			frappe.throw(_("Enter the value of work certified on this note."))
		self.retention_amount = self.gross_amount * flt(self.retention_percent) / 100
		remaining_advance = max(flt(agreement.advance_amount) - flt(agreement.advance_recovered), 0)
		if self.is_new() and not flt(self.advance_recovery):
			self.advance_recovery = calc.advance_recovery(
				self.gross_amount, agreement.advance_percent, agreement.advance_amount, agreement.advance_recovered
			)
		if flt(self.advance_recovery) > remaining_advance + 0.5:
			frappe.throw(_("Only {0} of the advance is still to be recovered.").format(frappe.format_value(remaining_advance, "Currency")))
		self.net_payable = self.gross_amount - self.retention_amount - flt(self.advance_recovery)

	@frappe.whitelist()
	def load_items(self):
		"""One row per payment milestone of the agreement (called from the form and on save)."""
		milestones = frappe.get_all(
			"Subcontract Agreement Milestone",
			filters={"parent": self.subcontract_agreement},
			fields=["name", "description", "phase", "amount"],
			order_by="idx asc",
		)
		if not milestones:
			contract_amount = frappe.db.get_value("Subcontract Agreement", self.subcontract_agreement, "contract_amount")
			self.append("items", {"description": _("Work certified"), "agreement_row": "", "contract_amount": contract_amount})
		for m in milestones:
			self.append(
				"items",
				{"description": m.description, "agreement_row": m.name, "phase": m.phase, "contract_amount": m.amount},
			)

	def previously_certified(self, agreement_row) -> float:
		total = frappe.db.sql(
			"""
			select sum(i.this_certificate) from `tabService Receipt Note Item` i
			inner join `tabService Receipt Note` n on n.name = i.parent
			where n.docstatus = 1 and n.subcontract_agreement = %s
				and ifnull(i.agreement_row, '') = %s and n.name != %s
			""",
			(self.subcontract_agreement, agreement_row or "", self.name or ""),
		)
		return flt(total[0][0]) if total else 0.0

	def before_submit(self):
		missing = []
		if not self.signed_service_receipt:
			missing.append(_("the signed Service Receipt Note"))
		if not self.milestone_completion_certificate:
			missing.append(_("the subcontractor's milestone completion certificate"))
		if self.certificate_type == "Final" and not self.operations_confirmation:
			missing.append(_("confirmation from Operations that the subcontractor met its obligations"))
		if missing:
			frappe.throw(_("Before this note can be submitted, attach or record: {0}.").format(", ".join(missing)))
		self.status = "Submitted"

	def on_submit(self):
		update_position(self.subcontract_agreement)
		notify_roles(
			FINANCE_ROLES,
			_("{0}: {1} certified for {2}. Create the supplier invoice.").format(
				self.name, frappe.format_value(self.gross_amount, "Currency"), self.supplier_name or self.supplier
			),
			doc=self,
		)

	def on_cancel(self):
		if self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel supplier invoice {0} first.").format(self.purchase_invoice))
		self.db_set("status", "Cancelled")
		update_position(self.subcontract_agreement)


@frappe.whitelist()
def make_purchase_invoice(source_name: str):
	"""Finance creates the supplier invoice from the certified note."""
	require_roles(*FINANCE_ROLES)
	note = frappe.get_doc("Service Receipt Note", source_name)
	if note.docstatus != 1:
		frappe.throw(_("Submit the Service Receipt Note first."))
	if note.purchase_invoice:
		frappe.throw(_("This note is already invoiced on {0}.").format(note.purchase_invoice))
	draft = frappe.db.get_value("Purchase Invoice", {"muhick_service_receipt_note": note.name, "docstatus": 0}, "name")
	if draft:
		return draft
	item = setting("subcontract_service_item")
	if not item:
		frappe.throw(_("Set the Item for Subcontract Invoices in Muhick Settings."))
	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{
			"supplier": note.supplier,
			"company": note.company,
			"project": note.project,
			"muhick_subcontract_agreement": note.subcontract_agreement,
			"muhick_service_receipt_note": note.name,
			"remarks": _("Service Receipt Note {0}. Retention to hold: {1}. Advance to recover: {2}. Net payable: {3}.").format(
				note.name,
				frappe.format_value(note.retention_amount, "Currency"),
				frappe.format_value(note.advance_recovery, "Currency"),
				frappe.format_value(note.net_payable, "Currency"),
			),
		}
	)
	invoice.append(
		"items",
		{
			"item_code": item,
			"qty": 1,
			"rate": note.gross_amount,
			"project": note.project,
			"muhick_cost_code": note.cost_code,
			"description": _("Subcontracted work certified on {0}").format(note.name),
		},
	)
	# saved as a draft on the server so ERPNext fills accounts and taxes and the certified rate is kept
	invoice.insert()
	return invoice.name
