# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The money in the company's bank and cash accounts, told project by project. Funds are not one pool: what a client pays
stays with its project, a project short of money is allocated some of another's (Resource Allocation), and refunds it
once it is paid. Everything here reads the postings on those accounts, so it always adds up to what the banks hold; what
is posted with no project stays apart, as money on no project. An allocation or refund changes hands inside one bank account
and posts nothing, so each account still adds up to what is in it."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.utils.common import FINANCE_ROLES, notify_roles

OPEN = ("Awaiting Transfer", "Outstanding", "Partly Refunded")
BANK_AND_CASH = ("Bank", "Cash")
# between the company's own accounts: nothing comes in or goes out
TRANSFERS = ("Internal Transfer", "Contra Entry")
NOT_ON_A_PROJECT = ""


def bank_accounts(company=None) -> list:
	filters = {"account_type": ("in", BANK_AND_CASH), "is_group": 0}
	if company:
		filters["company"] = company
	return frappe.get_all("Account", filters=filters, pluck="name")


def movements(company=None, upto=None) -> list:
	"""Every posting on the bank and cash accounts up to a date, oldest first, with its project. A bank line with no project
	takes the project of the rest of its entry, where that is one project."""
	accounts = bank_accounts(company)
	if not accounts:
		return []
	rows = frappe.db.sql(
		"""
		select posting_date, account, debit, credit, debit_in_account_currency, credit_in_account_currency, project, voucher_type,
			voucher_no, voucher_subtype, against, remarks
		from `tabGL Entry`
		where is_cancelled = 0 and account in %(accounts)s and posting_date <= %(upto)s
		order by posting_date, creation
		""",
		{"accounts": tuple(accounts), "upto": upto or nowdate()},
		as_dict=True,
	)
	vouchers = {row.voucher_no for row in rows if not row.project}
	if vouchers:
		found = defaultdict(set)
		for other in frappe.db.sql(
			"""
			select voucher_no, project from `tabGL Entry`
			where is_cancelled = 0 and voucher_no in %(vouchers)s and account not in %(accounts)s and ifnull(project, '') != ''
			""",
			{"vouchers": tuple(vouchers), "accounts": tuple(accounts)},
			as_dict=True,
		):
			found[other.voucher_no].add(other.project)
		for row in rows:
			if not row.project and len(found[row.voucher_no]) == 1:
				row.project = next(iter(found[row.voucher_no]))
	return rows


def allocations(company=None, upto=None) -> list:
	"""The approved allocations made by a date, each with its refunds up to then and what was still to refund."""
	upto = getdate(upto or nowdate())
	filters = {"docstatus": 1}
	if company:
		filters["company"] = company
	rows = [
		row
		for row in frappe.get_all(
			"Resource Allocation",
			filters=filters,
			fields=[
				"name", "transfer_date", "from_project", "to_project", "from_bank_account", "to_bank_account", "transfer_entry", "currency",
				"amount", "base_amount", "expected_refund_date", "status", "purpose",
			],
		)
		if getdate(row.transfer_date) <= upto
	]
	refunds = defaultdict(list)
	if rows:
		for refund in frappe.get_all(
			"Resource Allocation Refund",
			filters={"parent": ("in", [row.name for row in rows]), "parenttype": "Resource Allocation"},
			fields=["parent", "refund_date", "amount", "base_amount", "bank_amount", "from_bank_account", "to_bank_account", "reference"],
		):
			if getdate(refund.refund_date) <= upto:
				refunds[refund.parent].append(refund)
	for row in rows:
		row.refunds = refunds[row.name]
		row.refunded = sum(flt(refund.amount) for refund in row.refunds)
		row.outstanding = flt(row.amount) - row.refunded
		# in the company's currency: what a change in the rate shifted between the two projects stays where it fell
		row.base_refunded = sum(flt(refund.base_amount) for refund in row.refunds)
		row.base_net = flt(row.base_amount) - row.base_refunded
		row.base_outstanding = row.base_net if row.outstanding > 0.005 else 0.0
	return rows


def _change_hands(out, giver, taker, account, amount, base):
	"""Money passing between two projects inside one bank account, in its own currency and the company's. Nothing leaves the
	bank. One recorded before allocations named a bank is known only in the projects' totals."""
	if not account:
		return
	out[giver].held[account] -= flt(amount)
	out[giver].by_account[account] -= flt(base)
	out[taker].held[account] += flt(amount)
	out[taker].by_account[account] += flt(base)


def positions(company=None, upto=None) -> dict:
	"""{project, or NOT_ON_A_PROJECT: received, paid_out, own_funds, allocated_out, allocated_in, available, by_account, held}:
	by_account in the company's currency, held in each account's own."""
	out = defaultdict(
		lambda: frappe._dict(
			received=0.0, paid_out=0.0, own_funds=0.0, allocated_out=0.0, allocated_in=0.0, by_account=defaultdict(float), held=defaultdict(float)
		)
	)
	for row in movements(company, upto):
		position = out[row.project or NOT_ON_A_PROJECT]
		net = flt(row.debit) - flt(row.credit)
		position.own_funds += net
		position.by_account[row.account] += net
		position.held[row.account] += flt(row.debit_in_account_currency) - flt(row.credit_in_account_currency)
		if row.voucher_subtype not in TRANSFERS:
			position.received += flt(row.debit)
			position.paid_out += flt(row.credit)
	for allocation in allocations(company, upto):
		out[allocation.from_project].allocated_out += allocation.base_net
		out[allocation.to_project].allocated_in += allocation.base_net
		_change_hands(out, allocation.from_project, allocation.to_project, allocation.from_bank_account, allocation.amount, allocation.base_amount)
		for refund in allocation.refunds:
			_change_hands(out, allocation.to_project, allocation.from_project, refund.from_bank_account, refund.bank_amount, refund.base_amount)
	for position in out.values():
		position.available = position.own_funds - position.allocated_out + position.allocated_in
	return out


def available(project, company=None) -> float:
	return flt(positions(company)[project].available)


def held(project, account, company=None) -> float:
	"""What a project holds in one bank or cash account, in that account's own currency."""
	return flt(positions(company)[project].held.get(account))


def document_project(doctype, name):
	"""The one project a sales or purchase document is for, or None: its own, else its lines'. A sales order with none is
	still its project's where that project names it, and a sales invoice goes by its sales order."""
	if doctype not in ("Sales Invoice", "Sales Order", "Purchase Invoice", "Purchase Order"):
		return None
	project = frappe.db.get_value(doctype, name, "project")
	if project:
		return project
	if doctype == "Sales Order":
		return frappe.db.get_value("Project", {"sales_order": name}, "name")
	lines = set(frappe.get_all(f"{doctype} Item", filters={"parent": name}, pluck="project"))
	if len(lines) == 1 and None not in lines and "" not in lines:
		return lines.pop()
	if doctype == "Sales Invoice":
		orders = set(frappe.get_all("Sales Invoice Item", filters={"parent": name}, pluck="sales_order"))
		if len(orders) == 1 and None not in orders and "" not in orders:
			return document_project("Sales Order", orders.pop())
	return None


def tell_finance_of_receipt(payment):
	"""A project has been paid and still has allocated money to refund: Finance is told, so the money goes back."""
	project = payment.get("project")
	if payment.payment_type != "Receive" or not project:
		return
	owed = frappe.get_all(
		"Resource Allocation",
		filters={"to_project": project, "docstatus": 1, "status": ("in", OPEN)},
		fields=["name", "from_project", "base_outstanding_amount"],
	)
	if owed:
		notify_roles(
			FINANCE_ROLES,
			_("{0} has received {1} and still has {2} to refund to {3}.").format(
				project,
				frappe.format_value(payment.base_received_amount, "Currency"),
				frappe.format_value(sum(flt(row.base_outstanding_amount) for row in owed), "Currency"),
				", ".join(sorted({row.from_project for row in owed})),
			),
			doc=frappe._dict(doctype="Resource Allocation", name=owed[0].name),
		)
