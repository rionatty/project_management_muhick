# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Release of retention. Normally half falls due at practical completion and the rest when the
Defects Liability Period ends. Used both for retention the client holds on Muhick and for
retention Muhick holds on a subcontractor."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.doctype.subcontract_agreement.subcontract_agreement import update_position
from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils.common import FINANCE_ROLES, notify_roles, require_roles, setting


class RetentionRelease(Document):
	def validate(self):
		if self.retention_for == "Subcontractor":
			if not self.subcontract_agreement:
				frappe.throw(_("Select the subcontract agreement."))
			held, released, project = frappe.db.get_value(
				"Subcontract Agreement", self.subcontract_agreement, ["retention_held", "retention_released", "project"]
			)
			if project != self.project:
				frappe.throw(_("Agreement {0} belongs to project {1}.").format(self.subcontract_agreement, project))
		else:
			self.subcontract_agreement = None
			held, released = frappe.db.get_value("Project", self.project, ["muhick_retention_held", "muhick_retention_released"])
			self.check_stage()
		self.retention_held = flt(held)
		self.previously_released = flt(released)
		outstanding = self.retention_held - self.previously_released
		if flt(self.amount) <= 0 or flt(self.amount) > outstanding + 0.5:
			frappe.throw(_("Retention still held is {0}.").format(frappe.format_value(outstanding, "Currency")))
		self.balance_after = outstanding - flt(self.amount)

	def check_stage(self):
		stage = frappe.db.get_value("Project", self.project, "muhick_stage")
		if self.release_stage == "Practical Completion" and stage not in ("Practical Completion", "Full Completion"):
			frappe.throw(_("Record the Practical Completion Certificate before releasing retention at practical completion."))
		if self.release_stage == "End of Defects Liability" and stage != "Full Completion":
			frappe.throw(_("Record the Full Completion Certificate before releasing the remaining retention."))

	def on_submit(self):
		self.refresh_position()
		notify_roles(
			FINANCE_ROLES,
			_("Retention of {0} is released on {1} ({2}).").format(
				frappe.format_value(self.amount, "Currency"), self.project_name or self.project, _(self.release_stage)
			),
			doc=self,
		)

	def on_cancel(self):
		if self.sales_invoice and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel sales invoice {0} first.").format(self.sales_invoice))
		self.refresh_position()

	def refresh_position(self):
		if self.retention_for == "Subcontractor":
			update_position(self.subcontract_agreement)
		else:
			project_api.update_position(self.project)


@frappe.whitelist()
def make_sales_invoice(source_name: str):
	"""Only where retention is invoiced when it is released (Muhick Settings, Retention Invoicing)."""
	require_roles(*FINANCE_ROLES)
	release = frappe.get_doc("Retention Release", source_name)
	if release.docstatus != 1 or release.retention_for != "Client":
		frappe.throw(_("Only a submitted release of client retention can be invoiced."))
	if setting("retention_invoicing_method") != "Invoice Net of Retention":
		frappe.throw(_("Retention is already included in the certificate invoices; collect it against those invoices."))
	if release.sales_invoice:
		frappe.throw(_("This release is already invoiced on {0}.").format(release.sales_invoice))
	draft = frappe.db.get_value("Sales Invoice", {"muhick_retention_release": release.name, "docstatus": 0}, "name")
	if draft:
		return draft
	item = setting("claim_income_item")
	if not item:
		frappe.throw(_("Set the Item for Certified Work Invoices in Muhick Settings."))
	invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
			"customer": frappe.db.get_value("Project", release.project, "customer"),
			"company": release.company,
			"project": release.project,
			"muhick_retention_release": release.name,
		}
	)
	invoice.append(
		"items",
		{
			"item_code": item,
			"qty": 1,
			"rate": release.amount,
			"project": release.project,
			"description": _("Retention released: {0}").format(_(release.release_stage)),
		},
	)
	# saved as a draft on the server so ERPNext fills accounts and taxes and the certified rate is kept
	invoice.insert()
	return invoice.name
