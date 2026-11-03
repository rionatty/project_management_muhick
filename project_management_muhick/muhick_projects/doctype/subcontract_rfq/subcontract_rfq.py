# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Subcontract RFQ and evaluation.

The Project Manager issues the RFQ and emails or prints it for the subcontractors, on a print that shows them no budget
and no one else asked. The Procurement Manager and Finance Manager are told of each quotation recorded. The Project Manager
compares them on price, track record and current workload, selects one and sends the evaluation to the COO and then the
General Manager. Approval notifies Procurement and Finance, and Procurement prepares the Subcontract Agreement.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.utils.common import FM, PRM, notify_roles, setting

BEING_EVALUATED = ("Pending COO", "Pending General Manager", "Approved")
SUBCONTRACTOR_PRINT = "Subcontract RFQ"


class SubcontractRFQ(Document):
	def validate(self):
		suppliers = set()
		for row in self.quotations:
			if row.supplier in suppliers:
				frappe.throw(_("Quotations row {0}: {1} is listed twice.").format(row.idx, row.supplier))
			suppliers.add(row.supplier)
		selected = [r for r in self.quotations if r.is_selected]
		if len(selected) > 1:
			frappe.throw(_("Select only one subcontractor."))
		choice = selected[0] if selected else None
		self.selected_supplier = choice.supplier if choice else None
		self.selected_amount = flt(choice.quoted_amount) if choice else 0
		available = budget_engine.get_available(self.project) or {}
		self.budget_available = flt(available.get(self.cost_code))
		self.variance_to_budget = self.budget_available - self.selected_amount if choice else 0
		if self.workflow_state in BEING_EVALUATED:
			self.check_evaluation(choice)

	def check_evaluation(self, choice):
		received = [r for r in self.quotations if r.quotation_received and flt(r.quoted_amount) > 0]
		if not received:
			frappe.throw(_("Record at least one quotation received before submitting the evaluation."))
		if not choice or choice not in received:
			frappe.throw(_("Select the subcontractor to award, from those whose quotation was received."))
		if not (self.selection_justification or "").strip():
			frappe.throw(_("State the basis of selection: price, quality, timeline, track record and current workload."))
		minimum = int(setting("min_subcontract_quotations", 3) or 0)
		if len(received) < minimum:
			frappe.msgprint(
				_("Only {0} quotation(s) were received; {1} are normally required.").format(len(received), minimum),
				indicator="orange",
				alert=True,
			)

	def on_update(self):
		"""The Procurement Manager and Finance Manager are told of each quotation as it is recorded."""
		before = self.get_doc_before_save()
		known = {row.supplier for row in before.quotations if row.quotation_received} if before else set()
		new = [row.supplier for row in self.quotations if row.quotation_received and row.supplier not in known]
		if new:
			names = [frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier for supplier in new]
			notify_roles([PRM, FM], _("{0}: a quotation was recorded from {1}.").format(self.name, ", ".join(names)), doc=self)

	@frappe.whitelist()
	def email_rfq(self) -> dict:
		"""The RFQ to each subcontractor asked who has not quoted yet, separately, so none sees who else was asked."""
		from frappe.core.doctype.communication.email import make

		sent, no_email = [], []
		for row in self.quotations:
			if row.quotation_received:
				continue
			name = frappe.db.get_value("Supplier", row.supplier, "supplier_name") or row.supplier
			email = row.email_id or frappe.db.get_value("Supplier", row.supplier, "email_id")
			if not email:
				no_email.append(name)
				continue
			make(
				doctype=self.doctype,
				name=self.name,
				subject=_("Request for Quotation: {0}").format(self.title),
				content=_("Dear {0},<br><br>Please find attached our request for quotation for {1}. Please send your quotation by {2}.").format(
					name, self.title, formatdate(self.quotation_deadline) if self.quotation_deadline else _("the date given")
				),
				recipients=email,
				send_email=True,
				print_format=SUBCONTRACTOR_PRINT,
			)
			sent.append(name)
		return {"sent": sent, "no_email": no_email}


@frappe.whitelist()
def make_subcontract_agreement(source_name: str):
	rfq = frappe.get_doc("Subcontract RFQ", source_name)
	rfq.check_permission("read")
	if rfq.docstatus != 1:
		frappe.throw(_("The evaluation must be approved before the agreement is prepared."))
	if rfq.subcontract_agreement:
		frappe.throw(_("Agreement {0} already exists for this RFQ.").format(rfq.subcontract_agreement))
	choice = next(r for r in rfq.quotations if r.is_selected)
	doc = frappe.new_doc("Subcontract Agreement")
	doc.update(
		{
			"supplier": rfq.selected_supplier,
			"title": rfq.title,
			"project": rfq.project,
			"company": rfq.company,
			"cost_code": rfq.cost_code,
			"subcontract_rfq": rfq.name,
			"contract_amount": rfq.selected_amount,
			"scope_of_work": rfq.scope_of_work,
			"start_date": rfq.work_start,
			"end_date": rfq.work_end,
			"payment_terms": choice.payment_terms,
		}
	)
	return doc
