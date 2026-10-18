# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Service Delivery Note / Claim.

The claim mirrors the priced BOQ: each line shows the quantity previously claimed, the quantity
claimed now and the cumulative quantity, valued at the BOQ rate. Work is valued by what is
complete, never by what it cost. The client verifies the claim and issues an Interim Payment
Certificate; the Project Manager signs it and records it here, which notifies Finance to raise
the invoice for the certified amount as a single line.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from project_management_muhick.muhick_projects.utils import check_phase, phase_done, require_stage, validate_dates
from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import COO, FINANCE_ROLES, PM, notify_roles, require_roles, setting

CERTIFIED = ("Certified", "Invoiced", "Paid")
PROJECT_FIELDS = [
	"customer", "muhick_retention_percent", "muhick_advance_percent", "muhick_advance_amount",
	"muhick_advance_recovered", "muhick_boq",
]


class ProjectClaim(Document):
	def validate(self):
		require_stage(self.project, ("Execution", "Practical Completion"), _("Raising a claim"))
		if self.phase:
			check_phase(self.project, self.phase)
		validate_dates(self.period_from, self.period_to, _("Work Done From"), _("Work Done To"))
		project = frappe.db.get_value("Project", self.project, PROJECT_FIELDS, as_dict=True)
		if self.is_new() and not flt(self.retention_percent):
			self.retention_percent = project.muhick_retention_percent
		if self.claim_type == "Advance":
			self.set("items", [])
			self.materials_on_site = 0
			self.gross_this_claim = self.gross_previous = self.gross_to_date = 0
			if flt(self.advance_claimed) <= 0:
				frappe.throw(_("Enter the advance payment being claimed."))
			if flt(project.muhick_advance_amount) and flt(self.advance_claimed) > flt(project.muhick_advance_amount) + 0.5:
				frappe.throw(_("The contract advance is {0}.").format(frappe.format_value(project.muhick_advance_amount, "Currency")))
			self.advance_recovery = 0
		else:
			self.advance_claimed = 0
			self.set_item_values()
			if self.is_new() and not flt(self.advance_recovery):
				self.advance_recovery = calc.advance_recovery(
					self.gross_this_claim, project.muhick_advance_percent, project.muhick_advance_amount, project.muhick_advance_recovered
				)
		valuation = calc.claim_valuation(
			self.gross_this_claim if self.claim_type != "Advance" else 0,
			self.materials_on_site,
			self.retention_percent,
			self.advance_recovery,
			self.other_deductions,
			self.advance_claimed,
		)
		self.gross_claim = valuation["gross"]
		self.retention_amount = valuation["retention"]
		self.net_claim = valuation["net"]
		if self.gross_claim <= 0:
			frappe.throw(_("Enter the work done on this claim."))
		self.status = "Draft"

	def before_insert(self):
		last = frappe.db.sql("select max(claim_no) from `tabProject Claim` where project = %s and docstatus < 2", (self.project,))
		self.claim_no = (last[0][0] or 0) + 1

	def set_item_values(self):
		previous = get_previous_quantities(self.project, exclude=self.name)
		self.gross_this_claim = self.gross_previous = 0
		for row in self.items:
			row.previous_qty = flt(previous.get(row.source_row)) if row.source_row else 0
			row.cumulative_qty = flt(row.previous_qty) + flt(row.this_qty)
			if flt(row.contract_qty) > 0 and row.cumulative_qty > flt(row.contract_qty) + 1e-6:
				frappe.throw(
					_("Claim Items row {0}: {1} claimed to date is more than the contract quantity of {2}. Raise a Variation Order for the extra.").format(
						row.idx, f"{row.cumulative_qty:g}", f"{flt(row.contract_qty):g}"
					)
				)
			if flt(row.contract_qty) < 0 and row.cumulative_qty < flt(row.contract_qty) - 1e-6:
				frappe.throw(_("Claim Items row {0}: the omission claimed is more than the variation allows.").format(row.idx))
			row.this_amount = flt(row.this_qty) * flt(row.rate)
			row.cumulative_amount = row.cumulative_qty * flt(row.rate)
			row.percent_complete = row.cumulative_qty / flt(row.contract_qty) * 100 if flt(row.contract_qty) else 0
			self.gross_this_claim += row.this_amount
			self.gross_previous += flt(row.previous_qty) * flt(row.rate)
		self.gross_to_date = self.gross_previous + self.gross_this_claim

	def on_submit(self):
		"""Issued to the client (printed or emailed)."""
		self.db_set("status", "Submitted to Client")
		self.set_phase_billing("Claimed", only_from=("Completed",))

	def on_cancel(self):
		if self.status in ("Invoiced", "Paid"):
			frappe.throw(_("Cancel sales invoice {0} first.").format(self.sales_invoice))
		was_certified = self.status == "Certified"
		self.db_set("status", "Cancelled")
		self.set_phase_billing("Completed", only_from=("Claimed", "Certified"))
		if was_certified:
			update_certified_quantities(self.project)
			project_api.update_position(self.project)

	def set_phase_billing(self, status, only_from):
		"""Claimed / Certified is kept on the phase task; "Completed" clears it again."""
		if not self.phase:
			return
		task = frappe.db.get_value("Task", self.phase, ["status", "progress", "muhick_billing_status"], as_dict=True)
		current = task.muhick_billing_status or ("Completed" if phase_done(task) else "")
		if current in only_from:
			frappe.db.set_value(
				"Task", self.phase, "muhick_billing_status", "" if status == "Completed" else status, update_modified=False
			)

	@frappe.whitelist()
	def certify(
		self,
		certificate_no: str,
		certificate_date: str,
		certified_amount: float,
		certified_advance_recovery: float | None = None,
		remarks: str | None = None,
	):
		"""Record the client's Interim Payment Certificate, signed by the Project Manager."""
		require_roles(PM, COO)
		if self.docstatus != 1 or self.status != "Submitted to Client":
			frappe.throw(_("Only a claim submitted to the client can be certified."))
		if not self.signed_certificate:
			frappe.throw(_("Attach the signed certificate first."))
		certified_amount = flt(certified_amount)
		if certified_amount <= 0 or certified_amount > flt(self.gross_claim) + 0.5:
			frappe.throw(_("The certified amount must be more than zero and not more than the claim ({0}).").format(
				frappe.format_value(self.gross_claim, "Currency")))
		ratio = certified_amount / flt(self.gross_claim)
		for row in self.items:
			# quantities the client reduced are entered on the row; otherwise they follow the certified share
			qty = flt(row.certified_qty) if flt(row.certified_qty) else flt(row.this_qty) * ratio
			row.db_set("certified_qty", qty, update_modified=False)
		if self.claim_type == "Advance":
			retention = recovery = 0.0
		else:
			retention = certified_amount * flt(self.retention_percent) / 100
			recovery = flt(self.advance_recovery) * ratio if certified_advance_recovery is None else flt(certified_advance_recovery)
		self.db_set(
			{
				"certificate_no": certificate_no,
				"certificate_date": certificate_date,
				"certified_amount": certified_amount,
				"certified_retention": retention,
				"certified_advance_recovery": recovery,
				"net_certified": certified_amount - retention - recovery - flt(self.other_deductions) * ratio,
				"pm_signed": 1,
				"forwarded_to_finance_on": now_datetime(),
				"certification_remarks": remarks,
				"status": "Certified",
			}
		)
		update_certified_quantities(self.project)
		project_api.update_position(self.project)
		self.set_phase_billing("Certified", only_from=("Completed", "Claimed"))
		notify_roles(
			FINANCE_ROLES,
			_("Certificate {0} for {1} is signed ({2}). Raise the sales invoice.").format(
				certificate_no, self.project_name or self.project, frappe.format_value(certified_amount, "Currency")
			),
			doc=self,
		)

	@frappe.whitelist()
	def reject_by_client(self, reason: str):
		require_roles(PM, COO)
		if self.docstatus != 1 or self.status != "Submitted to Client":
			frappe.throw(_("Only a claim submitted to the client can be marked as rejected."))
		self.db_set({"status": "Rejected by Client", "certification_remarks": reason})
		self.set_phase_billing("Completed", only_from=("Claimed",))


def get_previous_quantities(project, exclude=None) -> dict:
	"""{source row: quantity already claimed}: certified quantities where the client has certified,
	claimed quantities where the claim is still with the client, plus anything certified before go-live."""
	previous = {}
	boq = frappe.db.get_value("Project", project, "muhick_boq")
	if boq:
		for row in frappe.get_all("Project BOQ Item", filters={"parent": boq}, fields=["name", "opening_certified_qty"]):
			previous[row.name] = flt(row.opening_certified_qty)
	rows = frappe.db.sql(
		"""
		select ci.source_row, sum(case when c.status in %(certified)s then ci.certified_qty else ci.this_qty end) as qty
		from `tabProject Claim Item` ci
		inner join `tabProject Claim` c on c.name = ci.parent
		where c.project = %(project)s and c.docstatus = 1 and c.status != 'Rejected by Client'
			and c.name != %(exclude)s and ifnull(ci.source_row, '') != ''
		group by ci.source_row
		""",
		{"project": project, "certified": CERTIFIED, "exclude": exclude or ""},
		as_dict=True,
	)
	for r in rows:
		previous[r.source_row] = flt(previous.get(r.source_row)) + flt(r.qty)
	return previous


def update_certified_quantities(project):
	"""Write the certified quantity back to every BOQ and variation line of the project."""
	certified = {
		r.source_row: flt(r.qty)
		for r in frappe.db.sql(
			"""
			select ci.source_row, sum(ci.certified_qty) as qty
			from `tabProject Claim Item` ci
			inner join `tabProject Claim` c on c.name = ci.parent
			where c.project = %(project)s and c.docstatus = 1 and c.status in %(certified)s
				and ifnull(ci.source_row, '') != ''
			group by ci.source_row
			""",
			{"project": project, "certified": CERTIFIED},
			as_dict=True,
		)
	}
	boq = frappe.db.get_value("Project", project, "muhick_boq")
	if boq:
		total = 0.0
		for row in frappe.get_all("Project BOQ Item", filters={"parent": boq}, fields=["name", "rate", "opening_certified_qty"]):
			qty = flt(row.opening_certified_qty) + certified.get(row.name, 0)
			frappe.db.set_value("Project BOQ Item", row.name, "certified_qty", qty, update_modified=False)
			total += qty * flt(row.rate)
		frappe.db.set_value("Project BOQ", boq, "certified_amount", total, update_modified=False)
	orders = frappe.get_all("Project Variation Order", filters={"project": project, "docstatus": 1}, pluck="name")
	if orders:
		for row in frappe.get_all("Project Variation Order Item", filters={"parent": ("in", orders)}, pluck="name"):
			frappe.db.set_value(
				"Project Variation Order Item", row, "certified_qty", certified.get(row, 0), update_modified=False
			)


@frappe.whitelist()
def get_claim_items(project: str, claim: str | None = None):
	"""BOQ and approved variation lines with the quantity already claimed on each."""
	frappe.has_permission("Project Claim", "read", throw=True)
	previous = get_previous_quantities(project, exclude=claim)
	items = []
	boq = frappe.db.get_value("Project", project, "muhick_boq")
	fields = ["name", "item_no", "description", "uom", "qty", "rate", "parent"]
	if boq:
		for row in frappe.get_all("Project BOQ Item", filters={"parent": boq}, fields=[*fields, "section"], order_by="idx asc"):
			items.append(_claim_row("BOQ", row, row.section, previous))
	orders = frappe.get_all("Project Variation Order", filters={"project": project, "docstatus": 1}, pluck="name", order_by="creation asc")
	if orders:
		for row in frappe.get_all(
			"Project Variation Order Item", filters={"parent": ("in", orders)}, fields=fields, order_by="parent asc, idx asc"
		):
			items.append(_claim_row("Variation", row, row.parent, previous))
	return items


def _claim_row(source_type, row, section, previous):
	done = flt(previous.get(row.name))
	return {
		"source_type": source_type,
		"source_row": row.name,
		"section": section,
		"item_no": row.item_no,
		"description": row.description,
		"uom": row.uom,
		"contract_qty": row.qty,
		"rate": row.rate,
		"previous_qty": done,
		"this_qty": 0,
		"cumulative_qty": done,
	}


@frappe.whitelist()
def make_sales_invoice(source_name: str):
	"""Finance raises the invoice from the signed certificate."""
	require_roles(*FINANCE_ROLES)
	claim = frappe.get_doc("Project Claim", source_name)
	if claim.docstatus != 1 or claim.status != "Certified":
		frappe.throw(_("The claim must be certified by the client and not yet invoiced."))
	draft = frappe.db.get_value("Sales Invoice", {"muhick_project_claim": claim.name, "docstatus": 0}, "name")
	if draft:
		return draft  # open the draft already raised for this certificate
	item = setting("claim_income_item")
	if not item:
		frappe.throw(_("Set the Item for Certified Work Invoices in Muhick Settings."))
	net_of_retention = setting("retention_invoicing_method") == "Invoice Net of Retention"
	amount = flt(claim.certified_amount) - (flt(claim.certified_retention) if net_of_retention else 0)
	invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
			"customer": claim.customer,
			"company": claim.company,
			"project": claim.project,
			"muhick_project_claim": claim.name,
			"remarks": _("Certificate {0} dated {1}. Gross certified {2}; retention {3}; advance recovered {4}; net certified {5}.").format(
				claim.certificate_no,
				claim.certificate_date,
				frappe.format_value(claim.certified_amount, "Currency"),
				frappe.format_value(claim.certified_retention, "Currency"),
				frappe.format_value(claim.certified_advance_recovery, "Currency"),
				frappe.format_value(claim.net_certified, "Currency"),
			),
		}
	)
	# the invoice shows one block total, not the BOQ breakdown
	invoice.append(
		"items",
		{
			"item_code": item,
			"qty": 1,
			"rate": amount,
			"project": claim.project,
			"description": _("{0} claim no. {1}, certificate {2}").format(_(claim.claim_type), claim.claim_no, claim.certificate_no),
		},
	)
	# saved as a draft on the server so ERPNext fills accounts and taxes and the certified rate is kept
	invoice.insert()
	return invoice.name
