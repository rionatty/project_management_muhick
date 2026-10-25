# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Weekly or monthly payment plan: the list of what Finance proposes to pay in the period, set
against the cash and bank position. It is approved by the Finance Manager and then the General
Manager, who may reduce an amount or hold a line. Payments are then raised from the approved
lines, so every supplier payment traces back to an approved plan."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.muhick_projects.utils import draft_status, validate_dates
from project_management_muhick.utils.common import FINANCE_ROLES, require_roles

DONE = ("Paid", "Held", "Not Executed")
OPEN_PLAN = ("Draft", "Pending Approval", "Approved")
# documents paid with a Payment Entry; the others are paid from their own form
PAID_BY_PAYMENT_ENTRY = ("Purchase Invoice", "Purchase Order", "Payment Request")
# documents whose funds can also be issued from the plan: the method that records them on the document
ISSUED_FROM_PLAN = {"Sales Requisition": "mark_paid", "Bid Security Request": "issue_funds"}


class PaymentPlan(Document):
	def validate(self):
		validate_dates(self.period_from, self.period_to, _("Period From"), _("Period To"))
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		seen = set()
		self.total_proposed = self.total_approved = 0
		for line in self.lines:
			key = (line.reference_doctype, line.reference_name)
			if key in seen:
				frappe.throw(_("Payment Lines row {0}: {1} is listed twice.").format(line.idx, line.reference_name))
			seen.add(key)
			self.set_line_details(line)
			self.check_not_on_another_plan(line)
			if flt(line.proposed_amount) <= 0:
				frappe.throw(_("Payment Lines row {0}: enter the amount proposed.").format(line.idx))
			if flt(line.proposed_amount) > flt(line.outstanding_amount) + 0.5:
				frappe.throw(
					_("Payment Lines row {0}: {1} proposed, but only {2} is outstanding.").format(
						line.idx,
						frappe.format_value(line.proposed_amount, "Currency"),
						frappe.format_value(line.outstanding_amount, "Currency"),
					)
				)
			if line.line_status == "Held":
				if not (line.hold_reason or "").strip():
					frappe.throw(_("Payment Lines row {0}: give the reason this payment is held.").format(line.idx))
				line.approved_amount = 0
			elif not flt(line.approved_amount) or flt(line.approved_amount) > flt(line.proposed_amount):
				line.approved_amount = line.proposed_amount
			self.total_proposed += flt(line.proposed_amount)
			self.total_approved += flt(line.approved_amount)
		self.total_available = sum(flt(a.balance) for a in self.accounts)
		self.status = draft_status(self)

	def set_line_details(self, line):
		"""Who is paid, for which project, how much is outstanding and when it falls due."""
		dt, dn = line.reference_doctype, line.reference_name
		source = frappe.db.get_value(dt, dn, "*", as_dict=True)
		if not source or source.docstatus != 1:
			frappe.throw(_("Payment Lines row {0}: {1} {2} is not an approved document.").format(line.idx, _(dt), dn))
		if dt == "Purchase Invoice":
			details = (source.supplier_name, source.project, source.outstanding_amount, source.due_date)
		elif dt == "Purchase Order":
			details = (source.supplier_name, source.project, flt(source.grand_total) - flt(source.advance_paid), source.schedule_date)
		elif dt == "Payment Request":
			details = (source.party, source.project, source.grand_total, source.transaction_date)
		elif dt == "Project Requisition":
			outstanding = flt(source.total_amount) - flt(source.amount_issued)
			details = (source.payee or source.requested_by, source.project, outstanding, source.required_by)
		elif dt == "Sales Requisition":
			outstanding = flt(source.total_amount) - flt(source.amount_issued)
			details = (source.requested_by, None, outstanding, source.required_by)
		elif dt == "Bid Security Request":
			outstanding = flt(source.funds_required) - flt(source.amount_issued)
			details = (source.requested_by, None, outstanding, source.required_by)
		elif dt == "Casual Sheet":
			outstanding = 0 if source.status == "Paid" else source.total_amount
			details = (_("Casual labour"), source.project, outstanding, source.period_to)
		else:
			outstanding = 0 if source.status == "Paid" else source.total_amount
			details = (source.claimant_name, source.project, outstanding, source.posting_date)
		line.party, line.project, outstanding, line.due_date = details
		if line.line_status != "Paid":
			line.outstanding_amount = flt(outstanding)

	def check_not_on_another_plan(self, line):
		other = frappe.db.sql(
			"""
			select p.name from `tabPayment Plan Line` l inner join `tabPayment Plan` p on p.name = l.parent
			where l.reference_doctype = %s and l.reference_name = %s and p.name != %s
				and p.docstatus < 2 and p.status in %s and l.line_status not in ('Paid', 'Not Executed')
			limit 1
			""",
			(line.reference_doctype, line.reference_name, self.name or "", OPEN_PLAN),
		)
		if other:
			frappe.throw(_("Payment Lines row {0}: {1} is already on payment plan {2}.").format(line.idx, line.reference_name, other[0][0]))

	def before_submit(self):
		for line in self.lines:
			if line.line_status == "Proposed":
				line.line_status = "Approved"
		self.status = "Approved"

	def before_update_after_submit(self):
		for line in self.lines:
			if line.line_status in ("Held", "Not Executed") and not (line.hold_reason or "").strip():
				frappe.throw(_("Payment Lines row {0}: give the reason this payment was not made.").format(line.idx))
		self.total_approved = sum(flt(l.approved_amount) for l in self.lines if l.line_status != "Held")
		self.total_paid = sum(flt(l.paid_amount) for l in self.lines)
		if self.status in ("Approved", "Closed"):
			self.status = "Closed" if all(l.line_status in DONE for l in self.lines) else "Approved"

	def on_cancel(self):
		if any(l.line_status == "Paid" for l in self.lines):
			frappe.throw(_("Payments have been made from this plan; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	def existing_keys(self) -> set:
		return {(l.reference_doctype, l.reference_name) for l in self.lines}

	def add_line(self, doctype, name, amount, description=None):
		if (doctype, name) not in self.existing_keys() and flt(amount) > 0:
			self.append(
				"lines",
				{"reference_doctype": doctype, "reference_name": name, "proposed_amount": amount, "description": description},
			)

	@frappe.whitelist()
	def get_balances(self):
		"""Cash and bank balances, to set the plan against what is actually available."""
		from erpnext.accounts.utils import get_balance_on

		self.set("accounts", [])
		for account in frappe.get_all(
			"Account",
			filters={"company": self.company, "is_group": 0, "account_type": ("in", ("Bank", "Cash"))},
			pluck="name",
			order_by="name asc",
		):
			self.append("accounts", {"account": account, "balance": get_balance_on(account, date=nowdate())})
		self.total_available = sum(flt(a.balance) for a in self.accounts)

	@frappe.whitelist()
	def get_due_invoices(self):
		"""Supplier invoices due by the end of the period (from the payables ageing)."""
		for inv in frappe.get_all(
			"Purchase Invoice",
			filters={
				"company": self.company,
				"docstatus": 1,
				"on_hold": 0,
				"outstanding_amount": (">", 0),
				"due_date": ("<=", self.period_to or nowdate()),
			},
			fields=["name", "outstanding_amount", "bill_no"],
			order_by="due_date asc",
		):
			self.add_line("Purchase Invoice", inv.name, inv.outstanding_amount, inv.bill_no)

	@frappe.whitelist()
	def get_payment_requests(self):
		"""Payment requests raised by the departments and not yet paid."""
		for req in frappe.get_all(
			"Payment Request",
			filters={
				"company": self.company,
				"docstatus": 1,
				"payment_request_type": "Outward",
				"status": ("not in", ("Paid", "Cancelled")),
			},
			fields=["name", "grand_total", "reference_name"],
		):
			self.add_line("Payment Request", req.name, req.grand_total, req.reference_name)

	@frappe.whitelist()
	def get_project_payables(self):
		"""Approved cash requisitions, bid security requests, casual sheets and expense claims waiting
		to be paid."""
		sources = (
			("Project Requisition", "purpose_title", "total_amount"), ("Casual Sheet", "project_name", "total_amount"),
			("Reimbursement Claim", "purpose", "total_amount"), ("Sales Requisition", "organisation", "total_amount"),
			("Bid Security Request", "organisation", "funds_required"),
		)
		for doctype, title, amount in sources:
			for doc in frappe.get_all(
				doctype,
				filters={"company": self.company, "docstatus": 1, "status": "Approved"},
				fields=["name", f"{amount} as amount", f"{title} as title"],
			):
				self.add_line(doctype, doc.name, doc.amount, doc.title)

	@frappe.whitelist()
	def make_payment(self, line: str):
		"""Raise the outgoing payment for one approved line, as a draft Payment Entry."""
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Payments can only be raised from an approved plan."))
		row = next((l for l in self.lines if l.name == line), None)
		if not row or row.line_status != "Approved":
			frappe.throw(_("This line is not approved for payment."))
		if row.payment_entry:
			return row.payment_entry
		if row.reference_doctype not in PAID_BY_PAYMENT_ENTRY:
			frappe.throw(_("{0} {1} is paid from its own form or with Issue Funds.").format(_(row.reference_doctype), row.reference_name))
		doctype, name = row.reference_doctype, row.reference_name
		if doctype == "Payment Request":
			doctype, name = frappe.db.get_value("Payment Request", name, ["reference_doctype", "reference_name"])
		entry = get_payment_entry(doctype, name, party_amount=flt(row.approved_amount))
		entry.muhick_payment_plan = self.name
		entry.muhick_payment_plan_line = row.name
		if row.mode_of_payment:
			entry.mode_of_payment = row.mode_of_payment
		if row.paid_from:
			entry.paid_from = row.paid_from
		entry.insert()
		frappe.db.set_value("Payment Plan Line", row.name, "payment_entry", entry.name, update_modified=False)
		return entry.name

	@frappe.whitelist()
	def issue_funds(
		self, line: str, issued_on: str | None = None, payment_reference: str | None = None, accountability_due_date: str | None = None
	):
		"""Pay an approved sales requisition or bid security request line: the document records the
		funds issued, and its line here is marked paid."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Funds can only be issued from an approved plan."))
		row = next((l for l in self.lines if l.name == line), None)
		if not row or row.line_status != "Approved":
			frappe.throw(_("This line is not approved for payment."))
		method = ISSUED_FROM_PLAN.get(row.reference_doctype)
		if not method:
			frappe.throw(_("Funds for {0} {1} are not issued from the plan.").format(_(row.reference_doctype), row.reference_name))
		doc = frappe.get_doc(row.reference_doctype, row.reference_name)
		# a requisition is accounted for by a date; a bid security request is not
		extra = {"accountability_due_date": accountability_due_date} if method == "mark_paid" else {}
		getattr(doc, method)(flt(row.approved_amount), issued_on or nowdate(), payment_reference, **extra)

	@frappe.whitelist()
	def refresh_lines(self):
		"""Pick up lines paid from their own form (requisitions, casual sheets, expense claims)."""
		if self.docstatus != 1:
			frappe.throw(_("Only an approved plan is refreshed."))
		for row in self.lines:
			if row.reference_doctype in PAID_BY_PAYMENT_ENTRY or row.line_status != "Approved":
				continue
			status = frappe.db.get_value(row.reference_doctype, row.reference_name, "status")
			if status in ("Paid", "Funds Issued", "Accountability Submitted", "Accounted", "Closed"):
				frappe.db.set_value(
					"Payment Plan Line",
					row.name,
					{"line_status": "Paid", "paid_amount": row.approved_amount},
					update_modified=False,
				)
		update_progress(self.name)


def update_progress(plan):
	"""Totals and status of a plan after one of its lines was paid or reversed."""
	lines = frappe.get_all("Payment Plan Line", filters={"parent": plan}, fields=["line_status", "paid_amount"])
	status = frappe.db.get_value("Payment Plan", plan, "status")
	values = {"total_paid": sum(flt(l.paid_amount) for l in lines)}
	if status in ("Approved", "Closed"):
		values["status"] = "Closed" if lines and all(l.line_status in DONE for l in lines) else "Approved"
	frappe.db.set_value("Payment Plan", plan, values, update_modified=False)


def settle_plan_line(doctype, name, amount):
	"""Funds issued for a document on its own form: its line on an approved plan is paid too."""
	for line, plan in frappe.db.sql(
		"""
		select l.name, l.parent from `tabPayment Plan Line` l inner join `tabPayment Plan` p on p.name = l.parent
		where l.reference_doctype = %s and l.reference_name = %s and l.line_status = 'Approved'
			and p.docstatus = 1 and p.status = 'Approved'
		""",
		(doctype, name),
	):
		frappe.db.set_value("Payment Plan Line", line, {"line_status": "Paid", "paid_amount": flt(amount)}, update_modified=False)
		update_progress(plan)


def on_payment(entry, cancelled=False):
	"""Payment Entry submitted or cancelled: mark the plan line it was raised from."""
	line = entry.get("muhick_payment_plan_line")
	if not line or not frappe.db.exists("Payment Plan Line", line):
		return
	if cancelled:
		values = {"line_status": "Approved", "paid_amount": 0, "payment_entry": None}
	else:
		values = {"line_status": "Paid", "paid_amount": entry.paid_amount, "payment_entry": entry.name}
	frappe.db.set_value("Payment Plan Line", line, values, update_modified=False)
	update_progress(frappe.db.get_value("Payment Plan Line", line, "parent"))


def approved_amount_for(entry) -> float | None:
	"""Approved amount of the plan line a payment was raised from; None if it is not on a plan."""
	plan, line = entry.get("muhick_payment_plan"), entry.get("muhick_payment_plan_line")
	if not plan:
		return None
	if frappe.db.get_value("Payment Plan", plan, ["docstatus", "status"]) != (1, "Approved"):
		frappe.throw(_("Payment Plan {0} is not an approved, open plan.").format(plan))
	if line:
		return flt(frappe.db.get_value("Payment Plan Line", {"name": line, "parent": plan}, "approved_amount"))
	# linked by hand: the references must be on the plan
	names = [r.reference_name for r in entry.get("references") or []]
	amounts = frappe.get_all(
		"Payment Plan Line",
		filters={"parent": plan, "reference_name": ("in", names), "line_status": "Approved"},
		pluck="approved_amount",
	) if names else []
	if not amounts:
		frappe.throw(_("None of the documents on this payment are approved lines of Payment Plan {0}.").format(plan))
	return sum(flt(a) for a in amounts)
