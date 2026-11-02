# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Weekly or monthly payment plan: the list of what Finance proposes to pay in the period, set
against the cash and bank position. It is approved by the Finance Manager and then the General
Manager, who may reduce an amount or hold a line. Payments are then raised from the approved
lines, so every supplier payment traces back to an approved plan. The money for a bid (its sales
requisitions and bid security requests) and the bank fees of guarantees and bonds falling due are
issued from the plan only. Each line says which bank account pays it; the position shows what that
leaves in each account. A supplier may go on the plan as soon as its requisition is approved: the
payment is then linked to the line and the requisition, and carried to the order and the invoice.

A plan's amounts are in the company's currency, so they add up and can be set against each other. An account in
that currency can pay anything; one in another currency pays only what is owed in that currency."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, getdate, nowdate

from project_management_muhick.muhick_projects.utils import draft_status, leaving_draft, validate_dates
from project_management_muhick.utils.common import FINANCE_ROLES, require_roles

DONE = ("Paid", "Held", "Not Executed")
OPEN_PLAN = ("Draft", "Pending Approval", "Approved")
# documents paid with a Payment Entry; the others are paid from their own form
PAID_BY_PAYMENT_ENTRY = ("Purchase Invoice", "Purchase Order", "Payment Request", "Procurement Requisition")
# documents whose funds can also be issued from the plan: the method that records them on the document
ISSUED_FROM_PLAN = {"Sales Requisition": "mark_paid", "Bid Security Request": "issue_funds", "Bank Instrument": "pay_fees"}
# a guarantee or bond whose bank fees are still charged
FEES_RUNNING = ("Requested", "Active", "Cancellation Requested")


class PaymentPlan(Document):
	def validate(self):
		validate_dates(self.period_from, self.period_to, _("Period From"), _("Period To"))
		if not self.lines:
			frappe.throw(_("Get the payments for this plan, or add one."))
		# the plan names itself from its period
		self.title = _("{0} Payment Plan: {1} to {2}").format(_(self.plan_type), formatdate(self.period_from), formatdate(self.period_to))
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		seen = set()
		self.total_proposed = self.total_approved = 0
		for line in self.lines:
			self.set_line_details(line)
			key = (line.reference_doctype, line.reference_name, line.supplier or None)
			if key in seen:
				frappe.throw(_("Payment Lines row {0}: {1} is listed twice.").format(line.idx, line.reference_name))
			seen.add(key)
			self.check_not_on_another_plan(line)
			self.give_plan_account(line)
			if line.paid_from:
				self.check_account_currency(line, line.paid_from)
			elif leaving_draft(self) and line.line_status != "Held":
				frappe.throw(_("Payment Lines row {0}: choose the bank account to pay {1} from.").format(line.idx, line.reference_name))
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
		self.set_position()
		self.status = draft_status(self)
		without = [str(line.idx) for line in self.lines if not line.paid_from]
		if self.pay_from and without and self.docstatus == 0:
			frappe.msgprint(
				_("{0} cannot pay what is owed on rows {1}. Choose their account.").format(self.pay_from, ", ".join(without)),
				indicator="orange",
				alert=True,
			)

	def home_currency(self) -> str:
		return frappe.get_cached_value("Company", self.company, "default_currency")

	def account_fits(self, account, line) -> bool:
		"""An account in the company's currency can pay anything; one in another only what is owed in that currency."""
		held_in = frappe.get_cached_value("Account", account, "account_currency")
		return held_in in (self.home_currency(), line.currency or self.owed_in(line)[0])

	def check_account_currency(self, line, account):
		if not self.account_fits(account, line):
			owed = line.currency or self.owed_in(line)[0]
			frappe.throw(
				_("Payment Lines row {0}: {1} is owed in {2}, and {3} is a {4} account. Pay it from a {5} account.").format(
					line.idx,
					line.reference_name,
					owed,
					account,
					frappe.get_cached_value("Account", account, "account_currency"),
					_(" or ").join(sorted({self.home_currency(), owed})),
				),
				title=_("Currency"),
			)

	def give_plan_account(self, line):
		if not line.paid_from and self.pay_from and self.account_fits(self.pay_from, line):
			line.paid_from = self.pay_from

	def owed_in(self, line) -> tuple:
		"""The currency a line is owed in, and its rate to the company's currency."""
		doctype, name = line.reference_doctype, line.reference_name
		home = self.home_currency()
		currency, rate = home, 1
		if doctype in ("Purchase Invoice", "Purchase Order"):
			currency, rate = frappe.db.get_value(doctype, name, ["currency", "conversion_rate"])
		elif doctype == "Payment Request":
			currency, source_doctype, source = frappe.db.get_value(doctype, name, ["currency", "reference_doctype", "reference_name"])
			rate = frappe.db.get_value(source_doctype, source, "conversion_rate") if currency != home else 1
		elif doctype == "Procurement Requisition":
			# a supplier who quoted in two currencies is paid in the company's
			quoted = {
				(row.currency, row.conversion_rate)
				for row in frappe.get_all(
					"Procurement Requisition Item",
					filters={"parent": name, "parenttype": "Procurement Requisition", "supplier": line.supplier},
					fields=["currency", "conversion_rate"],
				)
			}
			if len(quoted) == 1:
				currency, rate = quoted.pop()
		return currency or home, flt(rate) or 1

	def still_owed(self, doctype, source) -> float:
		"""What an invoice or order still owes, in the company's currency. An order fully billed is owed on its invoices."""
		if doctype == "Purchase Invoice":
			return self.in_company_currency(source, source.outstanding_amount)
		if flt(source.per_billed) >= 100:
			return 0.0
		total = flt(source.base_rounded_total) or flt(source.base_grand_total)
		return total - self.in_company_currency(source, source.advance_paid) - flt(source.muhick_paid_on_requisition)

	def left_on_request(self, line, source) -> float:
		"""What a payment request asks for, as far as the invoice or order behind it still owes that."""
		requested = flt(source.grand_total) * self.owed_in(line)[1]
		if source.reference_doctype not in ("Purchase Invoice", "Purchase Order"):
			return requested
		behind = frappe.db.get_value(source.reference_doctype, source.reference_name, "*", as_dict=True)
		return min(requested, self.still_owed(source.reference_doctype, behind)) if behind else requested

	def in_company_currency(self, source, amount) -> float:
		"""An amount a document holds in its supplier's account currency."""
		foreign = source.party_account_currency and source.party_account_currency != self.home_currency()
		return flt(amount) * (flt(source.conversion_rate) or 1) if foreign else flt(amount)

	def set_position(self):
		"""What each account pays out under this plan and what that leaves in it, in the account's own currency. The
		plan's total is in the company's."""
		home = self.home_currency()
		allocated = {}
		for line in self.lines:
			if line.paid_from and line.line_status not in ("Held", "Not Executed"):
				foreign = frappe.get_cached_value("Account", line.paid_from, "account_currency") != home
				amount = flt(line.approved_amount) / (flt(line.exchange_rate) or 1) if foreign else flt(line.approved_amount)
				allocated[line.paid_from] = allocated.get(line.paid_from, 0) + amount
		listed = {account.account for account in self.accounts}
		for name in allocated:
			if name not in listed:
				self.append("accounts", _account_position(name))
		for account in self.accounts:
			# listed before balances were kept in the account's own currency
			if not account.currency:
				account.update(_account_position(account.account))
			account.allocated = allocated.get(account.account, 0)
			account.balance_after = flt(account.balance) - flt(account.allocated)
		self.total_available = sum(flt(account.base_balance) for account in self.accounts)
		short = [a.account for a in self.accounts if flt(a.allocated) and flt(a.balance_after) < 0]
		if short and self.docstatus == 0:
			frappe.msgprint(
				_("This plan pays more than these accounts hold: {0}.").format(", ".join(short)), indicator="orange", alert=True
			)

	def set_line_details(self, line):
		"""Who is paid, for which project, how much is outstanding in the company's currency and when it falls due."""
		dt, dn = line.reference_doctype, line.reference_name
		source = frappe.db.get_value(dt, dn, "*", as_dict=True)
		if dt == "Bank Instrument":
			# it is kept, not approved: its fees are owed for as long as the bank charges for it
			if not source or source.status not in FEES_RUNNING:
				frappe.throw(_("Payment Lines row {0}: Bank Instrument {1} is closed, so no fees run on it.").format(line.idx, dn))
		elif not source or source.docstatus != 1:
			frappe.throw(_("Payment Lines row {0}: {1} {2} is not an approved document.").format(line.idx, _(dt), dn))
		if dt == "Purchase Invoice":
			details = (source.supplier_name, source.project, self.still_owed(dt, source), source.due_date)
		elif dt == "Purchase Order":
			details = (source.supplier_name, source.project, self.still_owed(dt, source), source.schedule_date)
		elif dt == "Procurement Requisition":
			details = self.requisition_details(line, source)
		elif dt == "Payment Request":
			details = (source.party, source.project, self.left_on_request(line, source), source.transaction_date)
		elif dt == "Project Requisition":
			outstanding = flt(source.total_amount) - flt(source.amount_issued)
			details = (source.payee or source.requested_by, source.project, outstanding, source.required_by)
		elif dt == "Sales Requisition":
			outstanding = flt(source.total_amount) - flt(source.amount_issued)
			details = (source.requested_by, None, outstanding, source.required_by)
		elif dt == "Bid Security Request":
			outstanding = flt(source.funds_required) - flt(source.amount_issued)
			details = (source.requested_by, None, outstanding, source.required_by)
		elif dt == "Bank Instrument":
			fees = self.fees_due(dn)
			bank = frappe.db.get_value("Bank Facility", source.bank_facility, "bank") if source.bank_facility else None
			details = (bank or source.title, source.project, sum(flt(f.amount) for f in fees), fees[0].due_date if fees else None)
		elif dt == "Casual Sheet":
			outstanding = 0 if source.status == "Paid" else source.total_amount
			details = (_("Casual labour"), source.project, outstanding, source.period_to)
		else:
			outstanding = 0 if source.status == "Paid" else source.total_amount
			details = (source.claimant_name, source.project, outstanding, source.posting_date)
		line.party, line.project, outstanding, line.due_date = details
		line.currency, line.exchange_rate = self.owed_in(line)
		if line.line_status != "Paid":
			line.outstanding_amount = flt(outstanding)

	def requisition_details(self, line, source):
		"""One supplier's share of an approved requisition, less what plans have paid on it so far."""
		rows = frappe.get_all(
			"Procurement Requisition Item",
			filters={"parent": source.name, "parenttype": "Procurement Requisition"},
			fields=["supplier", "supplier_name", "base_amount", "project", "schedule_date"],
		)
		suppliers = {row.supplier for row in rows}
		if not line.supplier and len(suppliers) == 1:
			line.supplier = rows[0].supplier
		if line.supplier not in suppliers:
			frappe.throw(_("Payment Lines row {0}: select which supplier on {1} is paid.").format(line.idx, source.name))
		if not line.mode_of_payment:
			line.mode_of_payment = source.mode_of_payment
		share = [row for row in rows if row.supplier == line.supplier]
		projects = {row.project for row in share}
		due_dates = [getdate(row.schedule_date) for row in share if row.schedule_date]
		return (
			share[0].supplier_name or line.supplier,
			projects.pop() if len(projects) == 1 else None,
			sum(flt(row.base_amount) for row in share) - paid_on_requisition(source.name, line.supplier),
			min(due_dates) if due_dates else source.requisition_date,
		)

	def other_plan(self, doctype, name, supplier=None) -> str | None:
		"""The other open plan a document is waiting on, for the supplier when it is a requisition."""
		other = frappe.db.sql(
			"""
			select p.name from `tabPayment Plan Line` l inner join `tabPayment Plan` p on p.name = l.parent
			where l.reference_doctype = %s and l.reference_name = %s and ifnull(l.supplier, '') = %s and p.name != %s
				and p.docstatus < 2 and p.status in %s and l.line_status not in ('Paid', 'Not Executed')
			limit 1
			""",
			(doctype, name, supplier or "", self.name or "", OPEN_PLAN),
		)
		return other[0][0] if other else None

	def check_not_on_another_plan(self, line):
		other = self.other_plan(line.reference_doctype, line.reference_name, line.supplier)
		if other:
			frappe.throw(_("Payment Lines row {0}: {1} is already on payment plan {2}.").format(line.idx, line.reference_name, other))

	def before_submit(self):
		for line in self.lines:
			if line.line_status == "Proposed":
				line.line_status = "Approved"
		self.status = "Approved"

	def before_update_after_submit(self):
		for line in self.lines:
			if line.line_status in ("Held", "Not Executed") and not (line.hold_reason or "").strip():
				frappe.throw(_("Payment Lines row {0}: give the reason this payment was not made.").format(line.idx))
			if line.paid_from and line.line_status not in DONE:
				self.check_account_currency(line, line.paid_from)
		self.total_approved = sum(flt(l.approved_amount) for l in self.lines if l.line_status != "Held")
		self.total_paid = sum(flt(l.paid_amount) for l in self.lines)
		self.set_position()
		if self.status in ("Approved", "Closed"):
			self.status = "Closed" if all(l.line_status in DONE for l in self.lines) else "Approved"

	def on_cancel(self):
		if any(l.line_status == "Paid" for l in self.lines):
			frappe.throw(_("Payments have been made from this plan; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	def existing_keys(self) -> set:
		return {(l.reference_doctype, l.reference_name, l.supplier or None) for l in self.lines}

	def add_line(self, doctype, name, amount=None, description=None, **values):
		"""A line for the amount given, or for what the document has outstanding in the company's currency. A row left
		empty on the form gives way to it."""
		if any(not line.reference_name for line in self.lines):
			self.lines[:] = [line for line in self.lines if line.reference_name]
			for idx, line in enumerate(self.lines, 1):
				line.idx = idx
		supplier = values.get("supplier")
		if (doctype, name, supplier) in self.existing_keys() or self.other_plan(doctype, name, supplier):
			return
		line = self.append("lines", {"reference_doctype": doctype, "reference_name": name, "description": description, **values})
		self.set_line_details(line)
		line.proposed_amount = line.approved_amount = flt(line.outstanding_amount if amount is None else amount)
		if line.proposed_amount > 0:
			self.give_plan_account(line)
		else:
			self.lines.pop()
		self.total_proposed = sum(flt(row.proposed_amount) for row in self.lines)
		self.total_approved = sum(flt(row.approved_amount) for row in self.lines)

	@frappe.whitelist()
	def get_balances(self):
		"""Cash and bank balances, to set the plan against what is actually available."""
		self.set("accounts", [])
		for account in frappe.get_all(
			"Account",
			filters={"company": self.company, "is_group": 0, "account_type": ("in", ("Bank", "Cash"))},
			pluck="name",
			order_by="name asc",
		):
			self.append("accounts", _account_position(account))
		self.set_position()

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
			fields=["name", "bill_no"],
			order_by="due_date asc",
		):
			self.add_line("Purchase Invoice", inv.name, description=inv.bill_no)

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
			fields=["name", "reference_name"],
		):
			self.add_line("Payment Request", req.name, description=req.reference_name)

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
	def get_approved_requisitions(self):
		"""Suppliers on approved requisitions, for what their terms call for now: the advance, or the whole amount on
		delivery. Credit waits for the invoice, though a line can still be added by hand."""
		for requisition in frappe.get_all(
			"Procurement Requisition",
			filters={"company": self.company, "docstatus": 1, "payment_terms_type": ("in", ("Advance", "On Delivery"))},
			fields=["name", "payment_terms_type", "advance_percent", "mode_of_payment"],
		):
			shares = {}
			for row in frappe.get_all(
				"Procurement Requisition Item",
				filters={"parent": requisition.name, "parenttype": "Procurement Requisition"},
				fields=["supplier", "supplier_name", "base_amount"],
			):
				shares.setdefault(row.supplier, [row.supplier_name, 0])[1] += flt(row.base_amount)
			for supplier, (supplier_name, amount) in shares.items():
				part = flt(requisition.advance_percent) / 100 if requisition.payment_terms_type == "Advance" else 1
				due = amount * part - paid_on_requisition(requisition.name, supplier)
				self.add_line(
					"Procurement Requisition", requisition.name, due, supplier_name, supplier=supplier, mode_of_payment=requisition.mode_of_payment
				)

	@frappe.whitelist()
	def get_bank_fees(self):
		"""The bank fees of guarantees and bonds falling due by the end of the period."""
		for instrument in frappe.get_all(
			"Bank Instrument", filters={"company": self.company, "status": ("in", FEES_RUNNING)}, fields=["name", "title"]
		):
			fees = self.fees_due(instrument.name)
			if fees:
				self.add_line("Bank Instrument", instrument.name, sum(flt(f.amount) for f in fees), instrument.title)

	def fees_due(self, instrument) -> list:
		"""An instrument's unpaid fees falling due by the end of the period, earliest first."""
		filters = {"parent": instrument, "parenttype": "Bank Instrument", "paid": 0}
		if self.period_to:
			filters["due_date"] = ("<=", self.period_to)
		return frappe.get_all("Bank Instrument Fee", filters=filters, fields=["name", "due_date", "amount"], order_by="due_date asc")

	@frappe.whitelist()
	def raise_payments(self) -> dict:
		"""A draft payment for every approved line paid with one. A line that cannot be raised does not hold up the others:
		it is reported, and one whose document has nothing left to pay is closed as not executed, saying why."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Payments can only be raised from an approved plan."))
		# the form may be behind, and a payment raised since must not be raised twice
		self.reload()
		result = {"created": [], "closed": [], "failed": []}
		muted = frappe.flags.mute_messages
		# what stops a line goes in the summary, not in a message of its own
		frappe.flags.mute_messages = True
		try:
			for row in self.lines:
				if row.line_status != "Approved" or row.payment_entry or row.reference_doctype not in PAID_BY_PAYMENT_ENTRY:
					continue
				frappe.db.savepoint("plan_payment")
				try:
					entry = self.make_payment(row.name)
				except frappe.ValidationError as e:
					frappe.db.rollback(save_point="plan_payment")
					result["failed"].append({"row": row.idx, "document": row.reference_name, "reason": str(e)})
					continue
				if entry:
					result["created"].append(entry)
				else:
					result["closed"].append(row.reference_name)
		finally:
			frappe.flags.mute_messages = muted
		update_progress(self.name)
		return result

	def make_payment(self, line: str):
		"""The outgoing payment of one approved line, as a draft Payment Entry, for no more than is left to pay. With
		nothing left, because it was paid by other means, the line is closed and there is no payment."""
		row = next((l for l in self.lines if l.name == line), None)
		if not row or row.line_status != "Approved":
			frappe.throw(_("This line is not approved for payment."))
		if row.payment_entry:
			return row.payment_entry
		if row.reference_doctype not in PAID_BY_PAYMENT_ENTRY:
			frappe.throw(_("{0} {1} is paid from its own form or with Issue Funds.").format(_(row.reference_doctype), row.reference_name))
		self.set_line_details(row)
		if flt(row.outstanding_amount) <= 0:
			reason = _("Nothing is left to pay on {0}.").format(row.reference_name)
			frappe.db.set_value("Payment Plan Line", row.name, {"line_status": "Not Executed", "hold_reason": reason}, update_modified=False)
			return None
		row.approved_amount = min(flt(row.approved_amount), flt(row.outstanding_amount))
		if not row.paid_from:
			frappe.throw(_("Payment Lines row {0}: choose the bank account to pay {1} from.").format(row.idx, row.reference_name))
		self.check_account_currency(row, row.paid_from)
		rate = flt(row.exchange_rate) or self.owed_in(row)[1]
		doctype, name = row.reference_doctype, row.reference_name
		if doctype == "Procurement Requisition":
			# against the order once it is approved; until then on account. The invoice takes up either as an advance
			order = frappe.db.get_value("Purchase Order", {"muhick_procurement_requisition": name, "supplier": row.supplier, "docstatus": 1}, "name")
			entry = _payment_against("Purchase Order", order, self.company, row, rate) if order else _payment_on_account(self.company, row, rate)
			entry.muhick_procurement_requisition = name
		else:
			if doctype == "Payment Request":
				doctype, name = frappe.db.get_value("Payment Request", name, ["reference_doctype", "reference_name"])
			entry = _payment_against(doctype, name, self.company, row, rate)
		entry.muhick_payment_plan = self.name
		entry.muhick_payment_plan_line = row.name
		if row.mode_of_payment:
			entry.mode_of_payment = row.mode_of_payment
		# ERPNext will not save a bank payment without these; the bank's own reference replaces this when it has paid
		entry.reference_no = entry.reference_no or self.name
		entry.reference_date = entry.reference_date or nowdate()
		entry.insert()
		frappe.db.set_value("Payment Plan Line", row.name, "payment_entry", entry.name, update_modified=False)
		return entry.name

	@frappe.whitelist()
	def issue_funds(
		self,
		line: str,
		issued_on: str | None = None,
		payment_reference: str | None = None,
		accountability_due_date: str | None = None,
		paid_from: str | None = None,
	):
		"""Pay an approved sales requisition, bid security request or bank fee line: the document records
		the funds issued (or the fees paid), and its line here is marked paid, from which account and when."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Funds can only be issued from an approved plan."))
		row = next((l for l in self.lines if l.name == line), None)
		if not row or row.line_status != "Approved":
			frappe.throw(_("This line is not approved for payment."))
		method = ISSUED_FROM_PLAN.get(row.reference_doctype)
		if not method:
			frappe.throw(_("Funds for {0} {1} are not issued from the plan.").format(_(row.reference_doctype), row.reference_name))
		paid_from = paid_from or row.paid_from
		if not paid_from:
			frappe.throw(_("Payment Lines row {0}: choose the bank account to pay {1} from.").format(row.idx, row.reference_name))
		self.check_account_currency(row, paid_from)
		doc = frappe.get_doc(row.reference_doctype, row.reference_name)
		# a requisition is accounted for by a date; a bid security request is not
		extra = {"accountability_due_date": accountability_due_date} if method == "mark_paid" else {}
		getattr(doc, method)(flt(row.approved_amount), issued_on or nowdate(), payment_reference, **extra)
		frappe.db.set_value(
			"Payment Plan Line",
			row.name,
			{"paid_from": paid_from, "paid_on": issued_on or nowdate(), "payment_reference": payment_reference},
			update_modified=False,
		)

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


def _account_position(account) -> dict:
	"""An account's balance in its own currency, and in the company's for the plan's total."""
	from erpnext.accounts.utils import get_balance_on

	return {
		"account": account,
		"currency": frappe.get_cached_value("Account", account, "account_currency"),
		"balance": flt(get_balance_on(account, date=nowdate())),
		"base_balance": flt(get_balance_on(account, date=nowdate(), in_account_currency=False)),
	}


def _payment_against(doctype, name, company, row, rate):
	"""ERPNext's own payment of a document for the line's amount. The line is in the company's currency; each side of
	the entry goes in its account's, at the document's rate, so the two sides agree."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.party import get_party_account_currency

	home = frappe.get_cached_value("Company", company, "default_currency")
	party_currency = home
	if doctype == "Purchase Invoice":
		party_currency = frappe.db.get_value(doctype, name, "party_account_currency") or home
	elif doctype == "Purchase Order":
		party_currency = get_party_account_currency("Supplier", row.supplier or frappe.db.get_value(doctype, name, "supplier"), company)
	bank_currency = frappe.get_cached_value("Account", row.paid_from, "account_currency")
	approved = flt(row.approved_amount)
	in_currency = lambda currency: approved if currency == home else approved / rate
	entry = get_payment_entry(
		doctype,
		name,
		party_amount=in_currency(party_currency),
		bank_account=row.paid_from,
		bank_amount=in_currency(bank_currency) if bank_currency != party_currency else None,
	)
	if home != bank_currency or home != party_currency:
		entry.source_exchange_rate = 1 if bank_currency == home else rate
		entry.target_exchange_rate = 1 if party_currency == home else rate
		entry.set_amounts()
	return entry


def _payment_on_account(company, row, rate):
	"""A supplier's payment before there is an order to set it against, built as ERPNext builds its own, with nothing
	allocated yet."""
	from erpnext.accounts.party import get_party_account

	home = frappe.get_cached_value("Company", company, "default_currency")
	entry = frappe.new_doc("Payment Entry")
	entry.update(
		{
			"payment_type": "Pay",
			"company": company,
			"posting_date": nowdate(),
			"reference_date": nowdate(),
			"party_type": "Supplier",
			"party": row.supplier,
			"project": row.project,
			"paid_from": row.paid_from,
			"paid_to": get_party_account("Supplier", row.supplier, company),
		}
	)
	entry.setup_party_account_field()
	entry.set_missing_values()
	# the line is in the company's currency; each side of the entry in its account's, at the quotation's rate
	entry.source_exchange_rate = 1 if entry.paid_from_account_currency == home else rate
	entry.target_exchange_rate = 1 if entry.paid_to_account_currency == home else rate
	entry.set_exchange_rate()
	entry.paid_amount = flt(row.approved_amount) / flt(entry.source_exchange_rate)
	entry.received_amount = flt(row.approved_amount) / flt(entry.target_exchange_rate)
	entry.set_amounts()
	return entry


def paid_on_requisition(requisition, supplier) -> float:
	"""What payment plans have paid a supplier on a requisition, in the company's currency."""
	lines = frappe.get_all(
		"Payment Plan Line",
		filters={"reference_doctype": "Procurement Requisition", "reference_name": requisition, "supplier": supplier, "line_status": "Paid"},
		pluck="paid_amount",
	)
	return sum(flt(amount) for amount in lines)


def paid_on_account(requisition, supplier) -> float:
	"""The part of that paid before the order was approved, which the order therefore does not count as its advance."""
	rows = frappe.db.sql(
		"""
		select sum(pe.base_paid_amount) from `tabPayment Entry` pe
		where pe.docstatus = 1 and pe.muhick_procurement_requisition = %s and pe.party = %s and not exists (
			select 1 from `tabPayment Entry Reference` ref
			where ref.parent = pe.name and ref.reference_doctype = 'Purchase Order'
		)
		""",
		(requisition, supplier),
	)
	return flt(rows[0][0]) if rows else 0.0


def carry_to_requisition(requisition, supplier):
	"""A payment on a requisition goes with it: the total on the requisition, the supplier's part on its order."""
	lines = frappe.get_all(
		"Payment Plan Line",
		filters={"reference_doctype": "Procurement Requisition", "reference_name": requisition, "line_status": "Paid"},
		pluck="paid_amount",
	)
	frappe.db.set_value("Procurement Requisition", requisition, "total_paid", sum(flt(amount) for amount in lines), update_modified=False)
	frappe.db.set_value(
		"Purchase Order",
		{"muhick_procurement_requisition": requisition, "supplier": supplier, "docstatus": ("<", 2)},
		"muhick_paid_on_requisition",
		paid_on_account(requisition, supplier),
		update_modified=False,
	)


def update_progress(plan):
	"""Totals and status of a plan after one of its lines was paid or reversed."""
	lines = frappe.get_all("Payment Plan Line", filters={"parent": plan}, fields=["line_status", "paid_amount"])
	status = frappe.db.get_value("Payment Plan", plan, "status")
	values = {"total_paid": sum(flt(l.paid_amount) for l in lines)}
	if status in ("Approved", "Closed"):
		values["status"] = "Closed" if lines and all(l.line_status in DONE for l in lines) else "Approved"
	frappe.db.set_value("Payment Plan", plan, values, update_modified=False)


@frappe.whitelist()
def get_payment_schedule(doctype: str, name: str) -> dict | None:
	"""The payment plan line of a request: which plan, its period, the amount and where it stands."""
	frappe.has_permission(doctype, "read", name, throw=True)
	lines = frappe.db.sql(
		"""
		select plan.name as plan, plan.period_from, plan.period_to, line.line_status, line.proposed_amount,
			line.approved_amount, line.hold_reason
		from `tabPayment Plan Line` line inner join `tabPayment Plan` plan on plan.name = line.parent
		where line.reference_doctype = %s and line.reference_name = %s and plan.docstatus < 2
		order by plan.period_from desc, plan.creation desc
		limit 1
		""",
		(doctype, name),
		as_dict=True,
	)
	return lines[0] if lines else None


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
		values = {"line_status": "Approved", "paid_amount": 0, "payment_entry": None, "paid_on": None, "payment_reference": None}
	else:
		values = {
			"line_status": "Paid",
			"paid_amount": flt(entry.base_paid_amount) or flt(entry.paid_amount),
			"payment_entry": entry.name,
			"paid_from": entry.paid_from,
			"paid_on": entry.posting_date,
			"payment_reference": entry.get("reference_no"),
		}
	frappe.db.set_value("Payment Plan Line", line, values, update_modified=False)
	update_progress(frappe.db.get_value("Payment Plan Line", line, "parent"))
	if entry.get("muhick_procurement_requisition"):
		carry_to_requisition(entry.muhick_procurement_requisition, entry.party)


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
