# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Service Receipt Note: the Project Manager certifies subcontracted work. It is the "goods received note" for services: Finance can only raise the
subcontractor's invoice against a submitted note, and the note can only be submitted with the
subcontractor's service delivery or interim certificate, the signed receipt and its milestone
completion certificate. Work on a milestone is certified once that milestone is complete. A final
certificate also needs Operations to confirm the subcontractor met its obligations.

The invoice is for the whole amount certified. The payment plan pays it less what is kept back: the
retention, until a Retention Release frees it, and the share of the advance the note recovers, which
the invoice takes up from the payment of that advance."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.doctype.subcontract_agreement.subcontract_agreement import update_position
from project_management_muhick.muhick_projects.utils import phase_done
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, notify_roles, require_roles, setting

AGREEMENT_FIELDS = ["contract_amount", "advance_percent", "advance_paid", "advance_recovered", "retention_percent", "status", "docstatus"]


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
			self.check_milestone_complete(row)
			self.gross_amount += flt(row.this_certificate)
		if self.gross_amount <= 0:
			frappe.throw(_("Enter the value of work certified on this note."))
		self.retention_amount = self.gross_amount * flt(self.retention_percent) / 100
		# only what has been paid out can be recovered
		remaining_advance = max(flt(agreement.advance_paid) - flt(agreement.advance_recovered), 0)
		if self.is_new() and not flt(self.advance_recovery):
			self.advance_recovery = calc.advance_recovery(
				self.gross_amount, agreement.advance_percent, agreement.advance_paid, agreement.advance_recovered
			)
		if flt(self.advance_recovery) > remaining_advance + 0.5:
			frappe.throw(_("Only {0} of the advance is still to be recovered.").format(frappe.format_value(remaining_advance, "Currency")))
		self.net_payable = self.gross_amount - self.retention_amount - flt(self.advance_recovery)

	def check_milestone_complete(self, row):
		if not flt(row.this_certificate) or not row.phase:
			return
		milestone = frappe.db.get_value("Task", row.phase, ["subject", "status", "progress"], as_dict=True) or {}
		if not phase_done(milestone):
			frappe.throw(
				_("Certified Work row {0}: milestone {1} is not complete yet, so its work cannot be certified.").format(
					row.idx, milestone.get("subject") or row.phase
				)
			)

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
		if not self.service_delivery_certificate:
			missing.append(_("the subcontractor's service delivery or interim certificate"))
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


def retention_still_held(agreement) -> dict:
	"""{note: what is still held of its retention}. What has been released comes off the oldest notes first."""
	released = sum(
		flt(amount)
		for amount in frappe.get_all(
			"Retention Release",
			filters={"subcontract_agreement": agreement, "docstatus": 1, "retention_for": "Subcontractor"},
			pluck="amount",
		)
	)
	held = {}
	for note in frappe.get_all(
		"Service Receipt Note",
		filters={"subcontract_agreement": agreement, "docstatus": 1},
		fields=["name", "retention_amount"],
		order_by="posting_date asc, creation asc",
	):
		freed = min(released, flt(note.retention_amount))
		released -= freed
		held[note.name] = flt(note.retention_amount) - freed
	return held


def held_back(note, taken_up=0) -> float:
	"""What the invoice of a note keeps back for now, in the company's currency: the note's retention still held, and the
	advance the note recovers as far as the invoice has not taken it up (taken_up: what it has)."""
	row = frappe.db.get_value("Service Receipt Note", note, ["subcontract_agreement", "advance_recovery"], as_dict=True)
	if not row:
		return 0.0
	return flt(retention_still_held(row.subcontract_agreement).get(note)) + max(flt(row.advance_recovery) - flt(taken_up), 0)


def _take_up_advance(invoice, note):
	"""The advance a note recovers, set against its invoice from the payments of that advance."""
	left = flt(note.advance_recovery)
	if left <= 0:
		return
	advances = frappe.get_all("Subcontract Advance", filters={"subcontract_agreement": note.subcontract_agreement, "docstatus": 1}, pluck="name")
	payments = set(
		frappe.get_all("Payment Entry", filters={"muhick_subcontract_advance": ("in", advances), "docstatus": 1}, pluck="name") if advances else ()
	)
	home = frappe.get_cached_value("Company", note.company, "default_currency")
	rate = flt(invoice.conversion_rate) or 1 if invoice.party_account_currency != home else 1
	for entry in invoice.get_advance_entries():
		if entry.reference_name not in payments or left <= 0.005:
			continue
		allocated = min(left / rate, flt(entry.amount))
		invoice.append(
			"advances",
			{
				"reference_type": entry.reference_type,
				"reference_name": entry.reference_name,
				"reference_row": entry.reference_row,
				"remarks": entry.remarks,
				"advance_amount": flt(entry.amount),
				"allocated_amount": allocated,
				"ref_exchange_rate": flt(entry.exchange_rate),
				"difference_posting_date": invoice.posting_date,
				"account": entry.get("paid_to"),
			},
		)
		left -= allocated * rate
	if invoice.get("advances"):
		invoice.save()


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
	_take_up_advance(invoice, note)
	return invoice.name
