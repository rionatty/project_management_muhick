# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Subcontract RFQ and evaluation.

The Project Manager issues the RFQ, records the quotations received, compares them on price,
track record and current workload, selects one and sends the evaluation to the COO and then the
General Manager. Approval notifies Procurement and Finance, and Procurement prepares the
Subcontract Agreement.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.utils.common import setting

BEING_EVALUATED = ("Pending COO", "Pending General Manager", "Approved")


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
