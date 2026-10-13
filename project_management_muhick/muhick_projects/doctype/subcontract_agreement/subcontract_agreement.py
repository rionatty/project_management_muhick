# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Subcontract agreement: scope, amount, payment terms (advance, milestones, retention) and
period. Approved by the COO and the General Manager. From approval it is a commitment on the
project budget at its full contract amount."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import draft_status, validate_dates
from project_management_muhick.utils.common import COO, PM, require_roles

RATINGS = ("rating_quality", "rating_timeliness", "rating_safety")


class SubcontractAgreement(Document):
	def validate(self):
		validate_dates(self.start_date, self.end_date, _("Start Date"), _("End Date"))
		if flt(self.contract_amount) <= 0:
			frappe.throw(_("Enter the contract amount."))
		self.advance_amount = flt(self.contract_amount) * flt(self.advance_percent) / 100
		if self.milestones:
			total = sum(flt(m.amount) for m in self.milestones)
			if abs(total - flt(self.contract_amount)) > 0.5:
				frappe.throw(
					_("Payment milestones total {0}; the contract amount is {1}.").format(
						frappe.format_value(total, "Currency"), frappe.format_value(self.contract_amount, "Currency")
					)
				)
		self.set_budget_status()
		self.balance_to_certify = flt(self.contract_amount)
		self.status = draft_status(self)

	def set_budget_status(self):
		self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, {self.cost_code: self.contract_amount})

	def before_submit(self):
		self.set_budget_status()
		budget_engine.enforce(self, "budget_action_on_subcontract", self.budget_status, self.budget_remarks)
		self.status = "Active"

	def on_submit(self):
		if self.subcontract_rfq:
			frappe.db.set_value("Subcontract RFQ", self.subcontract_rfq, "subcontract_agreement", self.name)
		frappe.db.set_value("Supplier", self.supplier, "muhick_is_subcontractor", 1)
		budget_engine.refresh_projects([self.project])

	def before_update_after_submit(self):
		given = [flt(self.get(f)) for f in RATINGS if flt(self.get(f))]
		self.overall_rating = sum(given) / len(given) if given else 0

	def on_cancel(self):
		if frappe.db.exists("Service Receipt Note", {"subcontract_agreement": self.name, "docstatus": 1}):
			frappe.throw(_("Work has been certified against this agreement; it cannot be cancelled."))
		self.db_set("status", "Cancelled")
		if self.subcontract_rfq:
			frappe.db.set_value("Subcontract RFQ", self.subcontract_rfq, "subcontract_agreement", None)
		budget_engine.refresh_projects([self.project])

	@frappe.whitelist()
	def complete(self):
		"""Close the subcontract. Its performance rating is kept for future evaluations."""
		require_roles(PM, COO)
		if self.docstatus != 1 or self.status != "Active":
			frappe.throw(_("Only an active agreement can be completed."))
		if not all(flt(self.get(f)) for f in RATINGS):
			frappe.throw(_("Rate the subcontractor on quality, timeliness and safety before completing the agreement."))
		self.db_set({"status": "Completed", "completed_on": nowdate()})
		# a completed subcontract is committed only for what was certified
		budget_engine.refresh_projects([self.project])


def update_position(agreement):
	"""Certified, retention and advance figures of an agreement, from its Service Receipt Notes."""
	notes = frappe.get_all(
		"Service Receipt Note",
		filters={"subcontract_agreement": agreement, "docstatus": 1},
		fields=["name", "gross_amount", "retention_amount", "advance_recovery"],
	)
	certified = sum(flt(n.gross_amount) for n in notes)
	released = sum(
		flt(a)
		for a in frappe.get_all(
			"Retention Release",
			filters={"subcontract_agreement": agreement, "docstatus": 1, "retention_for": "Subcontractor"},
			pluck="amount",
		)
	)
	contract_amount = flt(frappe.db.get_value("Subcontract Agreement", agreement, "contract_amount"))
	frappe.db.set_value(
		"Subcontract Agreement",
		agreement,
		{
			"certified_to_date": certified,
			"retention_held": sum(flt(n.retention_amount) for n in notes),
			"advance_recovered": sum(flt(n.advance_recovery) for n in notes),
			"retention_released": released,
			"balance_to_certify": contract_amount - certified,
		},
		update_modified=False,
	)
	by_row = {}
	if notes:
		for item in frappe.get_all(
			"Service Receipt Note Item",
			filters={"parent": ("in", [n.name for n in notes])},
			fields=["agreement_row", "this_certificate"],
		):
			by_row[item.agreement_row] = by_row.get(item.agreement_row, 0) + flt(item.this_certificate)
	for row in frappe.get_all("Subcontract Agreement Milestone", filters={"parent": agreement}, pluck="name"):
		frappe.db.set_value(
			"Subcontract Agreement Milestone", row, "certified_amount", by_row.get(row, 0), update_modified=False
		)
