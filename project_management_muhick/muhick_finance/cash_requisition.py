# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Cash given to a person against a requisition, and the accounting for it, the same for a project's and a bid's.

The weekly payment plan pays the money to the person's account: the company's staff advance account, with them as its
party. It stays there until they account for it. When Finance verifies the accountability, what was spent goes to the
expense accounts, line by line, out of their account. If they spent less they return the rest, and if they spent more the
company refunds them through the plan. Either way their account comes back to nothing for it.

A requisition paid before this has no journal entry of its payment: its money never went on anyone's account, so nothing is
posted for it now."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, fmt_money, now_datetime, nowdate

from project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan import check_expense_accounts, settle_plan_line
from project_management_muhick.muhick_projects.utils import validate_dates
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, notify, notify_roles, require_roles, setting

PAYMENT, ACCOUNTABILITY, RETURN, REFUND = "Payment", "Accountability", "Balance Returned", "Refund"
OPEN_ACCOUNTABILITY = ("Paid", "Accountability Submitted")
TOLERANCE = 0.005


def staff_account(company) -> str:
	"""The account people's money is held on, each under their own name as its party."""
	settings = frappe.get_cached_doc("Company", company)
	account = settings.get("muhick_staff_advance_account") or settings.get("default_employee_advance_account")
	if not account:
		frappe.throw(_("Set the Staff Advance Account on company {0}.").format(company), title=_("Staff Advance Account"))
	return account


class CashRequisition:
	"""Mixed into a requisition, whose items have an expense account and an amount and whose expenses account for them."""

	# what a line's expense account falls back on: the master, and the line's field that names it
	EXPENSE_SOURCE = None

	def after_money_moved(self):
		pass

	def _require_status(self, *allowed):
		if self.docstatus != 1 or self.status not in allowed:
			frappe.throw(_("This is not possible while the requisition is {0}.").format(_(self.status)))

	def requester_users(self) -> list:
		user = frappe.db.get_value("Employee", self.employee, "user_id") if self.employee else None
		return [u for u in {self.requested_by, user} if u]

	def money(self, amount) -> str:
		return fmt_money(amount, currency=frappe.get_cached_value("Company", self.company, "default_currency"))

	# ------------------------------------------------------------------ before approval
	def set_recipient(self):
		"""Whose account the money goes to: the one asking, unless someone else is named."""
		if not self.employee and self.requested_by:
			self.employee = frappe.db.get_value("Employee", {"user_id": self.requested_by, "status": "Active"}, "name")
		if self.employee:
			self.payee = frappe.db.get_value("Employee", self.employee, "employee_name")

	def check_ready_to_send(self):
		self.set_recipient()
		if not self.employee:
			frappe.throw(_("Choose who the money on {0} is given to.").format(self.name), title=_("Money Given To"))
		check_expense_accounts(self, self.items, self.EXPENSE_SOURCE)

	# ------------------------------------------------------------------ the payment
	def staff_row(self, debit=0, credit=0) -> dict:
		"""The person's side of an entry."""
		return {
			"account": staff_account(self.company),
			"party_type": "Employee",
			"party": self.employee,
			"debit_in_account_currency": flt(debit),
			"credit_in_account_currency": flt(credit),
			"project": self.get("project"),
		}

	def plan_entry(self) -> dict:
		"""What the plan's journal entry pays this requisition: its money to the person's account, or what they are refunded."""
		self.check_ready_to_send()
		step = REFUND if self.status == "Accounted" else PAYMENT
		return {"muhick_requisition_type": self.doctype, "muhick_requisition": self.name, "muhick_requisition_step": step}

	def _keep_accounts(self):
		"""Saved by the system, not typed: what it moves is not held to who may change the document, or to what may change on it."""
		self.flags.ignore_permissions = True
		self.flags.ignore_validate_update_after_submit = True
		self.flags.moving_money = True
		self.save()

	def mark_paid(
		self,
		amount_issued: float,
		issued_on: str | None = None,
		payment_reference: str | None = None,
		accountability_due_date: str | None = None,
	):
		"""The plan's journal entry is submitted: the money is on the person's account, or back with them."""
		require_roles(*FINANCE_ROLES)
		amount_issued = flt(amount_issued)
		if self.status == "Accounted":
			self._refunded(amount_issued, payment_reference)
			return
		self._require_status("Approved")
		if amount_issued <= 0 or amount_issued > flt(self.total_amount) + TOLERANCE:
			frappe.throw(_("The amount issued must be more than zero and not more than the approved amount."))
		issued_on = issued_on or nowdate()
		due = accountability_due_date or add_days(issued_on, setting("accountability_due_days", 7))
		validate_dates(issued_on, due, _("Issued On"), _("Account By"))
		self.check_ready_to_send()
		self.update(
			{
				"amount_issued": amount_issued,
				"issued_on": issued_on,
				"payment_reference": payment_reference,
				"accountability_due_date": due,
				"issue_entry": payment_reference,
				"paid_from": frappe.db.get_value("Journal Entry Account", {"parent": payment_reference, "credit": (">", 0)}, "account"),
				"status": "Paid",
			}
		)
		self._add_accountability_lines(issued_on)
		self._keep_accounts()
		settle_plan_line(self.doctype, self.name, amount_issued)
		self.after_money_moved()
		notify(
			self.requester_users(),
			_("{0} has been paid to your account. Account for it by {1}.").format(self.name, self.accountability_due_date),
			doc=self,
		)

	def _add_accountability_lines(self, on_date):
		"""A line of the accountability for each line requisitioned, on the same expense account, for the person to say what
		it cost."""
		self.set("expenses", [])
		for row in self.items:
			values = {"cost_code": row.get("cost_code")} if row.get("cost_code") else {}
			self.append(
				"expenses",
				{
					**values,
					"expense_date": on_date,
					"description": row.description or row.get("expense_type"),
					"expense_account": row.expense_account,
					"requested_amount": flt(row.amount),
					"amount": 0,
					"requisition_item": row.name,
				},
			)

	def _refunded(self, amount, reference):
		due = flt(self.reimbursement_due)
		paid = flt(self.reimbursed_amount) + amount
		if amount <= 0 or paid > due + TOLERANCE:
			frappe.throw(_("The refund still due is {0}.").format(self.money(due - flt(self.reimbursed_amount))))
		self.db_set({"reimbursed_amount": paid, "return_reference": reference, "status": "Closed" if paid >= due - TOLERANCE else "Accounted"})
		settle_plan_line(self.doctype, self.name, amount)
		notify(self.requester_users(), _("{0}: {1} has been refunded to you.").format(self.name, self.money(amount)), doc=self)

	def reverse_funds(self, reference=None):
		"""The plan's journal entry is cancelled, so the money is not out after all: not once it is being accounted for."""
		require_roles(*FINANCE_ROLES)
		if self.issue_entry and reference != self.issue_entry:
			amount = frappe.db.get_value("Journal Entry", reference, "total_debit")
			self.db_set({"reimbursed_amount": flt(self.reimbursed_amount) - flt(amount), "return_reference": None, "status": "Accounted"})
			return
		self._require_status("Paid")
		if any(flt(row.amount) for row in self.expenses):
			frappe.throw(_("Expenses are recorded against {0}. Remove them before cancelling its payment.").format(self.name))
		self.set("expenses", [])
		self.update(
			{
				"amount_issued": 0,
				"issued_on": None,
				"payment_reference": None,
				"accountability_due_date": None,
				"issue_entry": None,
				"paid_from": None,
				"status": "Approved",
			}
		)
		self._keep_accounts()
		self.after_money_moved()

	# ------------------------------------------------------------------ the accountability
	def before_update_after_submit(self):
		"""The person records what was spent, on the approved requisition."""
		if not self.flags.moving_money:
			before = self.get_doc_before_save()
			lines = lambda doc: [(e.amount, e.get("cost_code"), e.expense_account) for e in doc.expenses]
			if before and lines(before) != lines(self) and self.status not in OPEN_ACCOUNTABILITY:
				frappe.throw(_("Expenses can only be recorded after the money is issued and before the accountability is verified."))
		self.set_position()

	def set_position(self):
		self.amount_spent = sum(flt(e.amount) for e in self.expenses)
		position = calc.accountability_position(self.amount_issued, self.amount_spent, self.returned_amount)
		self.balance_to_return = position["balance_to_return"]
		self.reimbursement_due = position["reimbursement_due"]

	def check_accountability(self):
		"""Every line says what it cost, on which expense account, and why it is not what was asked for."""
		if not self.expenses:
			frappe.throw(_("Record the expenses incurred, with receipts, before submitting the accountability."))
		check_expense_accounts(self, self.expenses, self.EXPENSE_SOURCE)
		for row in self.expenses:
			if (row.reason or "").strip():
				continue
			if row.requisition_item and abs(flt(row.amount) - flt(row.requested_amount)) > TOLERANCE:
				frappe.throw(_("Expenses row {0}: give the reason it is not what was requested.").format(row.idx), title=_("Reason Needed"))
			if not row.requisition_item and flt(row.amount):
				frappe.throw(_("Expenses row {0} was not on the requisition: give the reason.").format(row.idx), title=_("Reason Needed"))

	@frappe.whitelist()
	def submit_accountability(self):
		"""The person hands in the accountability with receipts."""
		self._require_status("Paid")
		self.check_accountability()
		self.set_position()
		self.db_set(
			{
				"amount_spent": self.amount_spent,
				"balance_to_return": self.balance_to_return,
				"reimbursement_due": self.reimbursement_due,
				"accountability_submitted_on": now_datetime(),
				"status": "Accountability Submitted",
			}
		)
		notify_roles(FINANCE_ROLES, _("Accountability for {0} is ready to verify.").format(self.name), doc=self)

	@frappe.whitelist()
	def verify_accountability(self):
		"""Finance verifies it against the receipts, which posts what was spent to the expense accounts."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accountability Submitted")
		self.check_accountability()
		self.set_position()
		settled = not self.balance_to_return and not self.reimbursement_due
		self.db_set(
			{
				"amount_spent": self.amount_spent,
				"balance_to_return": self.balance_to_return,
				"reimbursement_due": self.reimbursement_due,
				"accountability_entry": self._post_accountability(),
				"verified_by": frappe.session.user,
				"verified_on": now_datetime(),
				"status": "Closed" if settled else "Accounted",
			}
		)
		self.after_money_moved()
		if self.balance_to_return:
			notify(self.requester_users(), _("{0}: return the unspent balance of {1} to Finance.").format(self.name, self.money(self.balance_to_return)), doc=self)
		elif self.reimbursement_due:
			notify_roles(
				FINANCE_ROLES,
				_("{0}: {1} is due back to {2}. It goes on the next payment plan.").format(self.name, self.money(self.reimbursement_due), self.payee or self.requested_by),
				doc=self,
			)

	def _new_entry(self, step, voucher_type, remark):
		entry = frappe.new_doc("Journal Entry")
		entry.update(
			{
				"voucher_type": voucher_type,
				"company": self.company,
				"posting_date": nowdate(),
				"user_remark": remark,
				"muhick_requisition_type": self.doctype,
				"muhick_requisition": self.name,
				"muhick_requisition_step": step,
			}
		)
		return entry

	def _cost_center(self):
		project = self.get("project")
		return (project and frappe.db.get_value("Project", project, "cost_center")) or frappe.get_cached_value("Company", self.company, "cost_center")

	def _post_accountability(self) -> str | None:
		spent = [row for row in self.expenses if flt(row.amount)]
		if not self.issue_entry or not spent:
			return None
		cost_center = self._cost_center()
		entry = self._new_entry(ACCOUNTABILITY, "Journal Entry", _("Accountability for {0}, {1}").format(self.name, self.payee or self.employee))
		for row in spent:
			entry.append(
				"accounts",
				{
					"account": row.expense_account,
					"debit_in_account_currency": flt(row.amount),
					"project": self.get("project"),
					"cost_center": cost_center,
					"user_remark": row.description,
				},
			)
		entry.append("accounts", self.staff_row(credit=sum(flt(row.amount) for row in spent)))
		return _submitted(entry)

	@frappe.whitelist()
	def record_return(self, amount: float, reference: str | None = None, bank_account: str | None = None, on_date: str | None = None):
		"""Finance receives the unspent balance back: it leaves the person's account and is in the bank again."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accounted")
		outstanding = flt(self.balance_to_return) - flt(self.returned_amount)
		amount = flt(amount)
		if amount <= 0 or amount > outstanding + TOLERANCE:
			frappe.throw(_("The balance still to be returned is {0}.").format(self.money(outstanding)))
		posted = self._post_return(amount, reference, bank_account, on_date or nowdate()) if self.issue_entry else None
		returned = flt(self.returned_amount) + amount
		self.db_set(
			{
				"returned_amount": returned,
				"return_reference": reference or posted,
				"status": "Closed" if returned >= flt(self.balance_to_return) - TOLERANCE else "Accounted",
			}
		)
		self.after_money_moved()

	def _post_return(self, amount, reference, bank_account, on_date) -> str:
		if not bank_account:
			frappe.throw(_("Choose the bank or cash account the money came back to."))
		home = frappe.get_cached_value("Company", self.company, "default_currency")
		held_in, kind = frappe.get_cached_value("Account", bank_account, ["account_currency", "account_type"])
		if held_in != home:
			frappe.throw(_("{0} is a {1} account. Choose a {2} account.").format(bank_account, held_in, home), title=_("Currency"))
		entry = self._new_entry(
			RETURN, "Cash Entry" if kind == "Cash" else "Bank Entry", _("Balance returned on {0} by {1}").format(self.name, self.payee or self.employee)
		)
		entry.update({"posting_date": on_date, "cheque_no": reference or self.name, "cheque_date": on_date})
		entry.append("accounts", {"account": bank_account, "debit_in_account_currency": amount, "project": self.get("project")})
		entry.append("accounts", self.staff_row(credit=amount))
		return _submitted(entry)

	@frappe.whitelist()
	def record_reimbursement(self, reference: str | None = None):
		"""One paid before money went through people's accounts: Finance notes the refund, which posts nothing. Any other is
		refunded from the payment plan."""
		require_roles(*FINANCE_ROLES)
		self._require_status("Accounted")
		if self.issue_entry:
			frappe.throw(_("This refund is paid from the payment plan."))
		if not flt(self.reimbursement_due):
			frappe.throw(_("No reimbursement is due on this requisition."))
		self.db_set({"reimbursed_amount": self.reimbursement_due, "return_reference": reference, "status": "Closed"})


def _submitted(entry) -> str:
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


def on_entry_cancelled(entry):
	"""An accountability's or returned balance's journal entry cancelled: the requisition goes back to before it."""
	step = entry.get("muhick_requisition_step")
	if step not in (ACCOUNTABILITY, RETURN):
		return
	doc = frappe.get_doc(entry.muhick_requisition_type, entry.muhick_requisition)
	if step == RETURN:
		doc.db_set({"returned_amount": flt(doc.returned_amount) - flt(entry.total_debit), "return_reference": None, "status": "Accounted"})
	else:
		if flt(doc.returned_amount) or flt(doc.reimbursed_amount):
			frappe.throw(_("Money has come back or been refunded on {0}. Cancel that first.").format(doc.name))
		doc.db_set({"accountability_entry": None, "verified_by": None, "verified_on": None, "status": "Accountability Submitted"})
	doc.after_money_moved()


def _names_like(txt) -> dict:
	return {"name": ("like", f"%{txt}%")}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""The company's active staff, for whoever raises a requisition, who may not read the employee records."""
	_check_can_raise()
	return frappe.get_all(
		"Employee",
		filters={"company": frappe._dict(filters or {}).company, "status": "Active"},
		or_filters={**_names_like(txt), "employee_name": ("like", f"%{txt}%")},
		fields=["name", "employee_name"],
		order_by="employee_name",
		limit_start=start,
		limit_page_length=page_len,
		as_list=not as_dict,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def expense_account_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""The company's expense accounts, for whoever maps a line to one, who may not read the chart of accounts."""
	_check_can_raise()
	return frappe.get_all(
		"Account",
		filters={"company": frappe._dict(filters or {}).company, "is_group": 0, "disabled": 0, "root_type": "Expense"},
		or_filters={**_names_like(txt), "account_name": ("like", f"%{txt}%")},
		fields=["name", "account_name"],
		order_by="name",
		limit_start=start,
		limit_page_length=page_len,
		as_list=not as_dict,
	)


def _check_can_raise():
	if not any(frappe.has_permission(doctype, "read") for doctype in ("Project Requisition", "Sales Requisition", "Casual Sheet")):
		frappe.throw(_("You cannot pick from this list."), frappe.PermissionError)
