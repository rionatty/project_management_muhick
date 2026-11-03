# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Money attached to one project allocated to another. Funds are held project by project, not in one pool, and the money is
in a bank: when a project runs ahead of its own receipts it uses what another project holds in a bank account (often a
client advance) and refunds it once it is paid. The Finance Manager or the department that needs the money prepares the
request and the General Manager approves it.

In the bank it comes from, the money changes hands between the two projects and nothing posts. If it is wanted in another
bank, a draft internal transfer takes it there on the receiving project, whose total that does not change. A refund works
the same way back, and the allocation stays outstanding until refunded, so the position of every project is known."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, fmt_money, nowdate

from project_management_muhick.muhick_finance import funds
from project_management_muhick.muhick_projects.utils import draft_status, leaving_draft
from project_management_muhick.utils.common import FINANCE_ROLES, notify, notify_roles, project_manager_of, require_roles

AWAITING = "Awaiting Transfer"
TOLERANCE = 0.005


def _home(company) -> str:
	return frappe.get_cached_value("Company", company, "default_currency")


def _currency_of(account) -> str:
	return frappe.get_cached_value("Account", account, "account_currency")


def _project_name(project) -> str:
	return frappe.db.get_value("Project", project, "project_name") or project


def _market_rate(foreign, home, on_date) -> float:
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(foreign, home, on_date))


def _rate(company, given, on_date, *currencies) -> float:
	"""The one rate a document uses, for the one currency on it besides the company's."""
	home = _home(company)
	foreign = set(currencies) - {home}
	if not foreign:
		return 1.0
	if len(foreign) > 1:
		frappe.throw(
			_("{0} cannot be exchanged directly. Move the money through a {1} account.").format(_(" and ").join(sorted(foreign)), home),
			title=_("Currency"),
		)
	rate = flt(given) or _market_rate(foreign.pop(), home, on_date)
	if rate <= 0:
		frappe.throw(_("Enter the exchange rate."), title=_("Currency"))
	return rate


def _converted(amount, currency, wanted, home, rate) -> float:
	"""An amount in one currency, in another."""
	if currency == wanted:
		return flt(amount)
	base = flt(amount) if currency == home else flt(amount) * flt(rate)
	return base if wanted == home else base / flt(rate)


def _make_transfer(allocation, project, paid_from, paid_to, paid_amount, received_amount, rate, refund=None) -> str:
	"""A draft between two of the company's accounts, on the project whose money it now is. The document's name stands in for
	the bank's reference, which is entered before it is submitted."""
	home = _home(allocation.company)
	entry = frappe.new_doc("Payment Entry")
	entry.update(
		{
			"payment_type": "Internal Transfer",
			"company": allocation.company,
			"posting_date": nowdate(),
			"reference_date": nowdate(),
			"reference_no": allocation.name,
			"project": project,
			"paid_from": paid_from,
			"paid_to": paid_to,
			"paid_amount": paid_amount,
			"received_amount": received_amount,
			"source_exchange_rate": 1 if _currency_of(paid_from) == home else rate,
			"target_exchange_rate": 1 if _currency_of(paid_to) == home else rate,
			"muhick_resource_allocation": allocation.name,
			"muhick_allocation_refund": refund,
		}
	)
	entry.insert(ignore_permissions=True)
	return entry.name


class ResourceAllocation(Document):
	def validate(self):
		if self.from_project == self.to_project:
			frappe.throw(_("Select two different projects."))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount."))
		if not self.from_bank_account:
			frappe.throw(_("Select the bank account the money is in."))
		self.to_bank_account = self.to_bank_account or self.from_bank_account
		self.set_amounts()
		self.outstanding_amount = flt(self.amount)
		self.base_outstanding_amount = flt(self.base_amount)
		self.status = draft_status(self)
		self.check_funds()

	def set_amounts(self):
		"""The amount is in the From account's currency; the projects' figures are told in the company's."""
		home = _home(self.company)
		self.company_currency = home
		self.currency = _currency_of(self.from_bank_account)
		self.to_currency = _currency_of(self.to_bank_account)
		self.exchange_rate = _rate(self.company, self.exchange_rate, self.transfer_date, self.currency, self.to_currency)
		self.base_amount = _converted(self.amount, self.currency, home, home, self.exchange_rate)
		self.received_amount = _converted(self.amount, self.currency, self.to_currency, home, self.exchange_rate)

	def check_funds(self):
		"""It must be money the project has in that bank. A draft can be saved, but it goes for approval, and is approved, only
		if the money is there."""
		held = funds.held(self.from_project, self.from_bank_account, self.company)
		if flt(self.amount) <= held + TOLERANCE:
			return
		message = _("{0} holds only {1} in {2}.").format(
			_project_name(self.from_project), fmt_money(held, currency=self.currency), self.from_bank_account
		)
		if leaving_draft(self):
			frappe.throw(message, title=_("Not Enough Funds"))
		frappe.msgprint(message, indicator="orange", alert=True)

	def moves_between_banks(self) -> bool:
		return self.from_bank_account != self.to_bank_account

	def before_submit(self):
		self.refunded_amount = 0
		self.outstanding_amount = flt(self.amount)
		self.base_outstanding_amount = flt(self.base_amount)
		self.status = AWAITING if self.moves_between_banks() else "Outstanding"

	def on_submit(self):
		if not self.moves_between_banks():
			return
		# Finance moves the money: a draft that cannot be raised is theirs to raise from the form, and does not stop the approval
		muted = frappe.flags.mute_messages
		frappe.flags.mute_messages = True
		frappe.db.savepoint("allocation_transfer")
		try:
			transfer = self.raise_own_transfer()
		except Exception:
			frappe.db.rollback(save_point="allocation_transfer")
			frappe.log_error(title=f"Muhick: could not raise the transfer of {self.name}")
			transfer = None
		finally:
			frappe.flags.mute_messages = muted
		message = (
			_("{0} is approved. Transfer {1} from {2} to {3} is waiting: enter the bank's reference and submit it.").format(
				self.name, transfer, self.from_bank_account, self.to_bank_account
			)
			if transfer
			else _("{0} is approved, but the transfer from {1} to {2} could not be raised. Raise it from Create on the allocation.").format(
				self.name, self.from_bank_account, self.to_bank_account
			)
		)
		notify_roles(FINANCE_ROLES, message, doc=self)

	def raise_own_transfer(self) -> str:
		transfer = _make_transfer(
			self, self.to_project, self.from_bank_account, self.to_bank_account, self.amount, self.received_amount, self.exchange_rate
		)
		self.db_set("transfer_entry", transfer, update_modified=False)
		return transfer

	def before_update_after_submit(self):
		# approved before allocations named a bank
		if not self.from_bank_account:
			self.flags.ignore_mandatory = True
		self.refunded_amount = sum(flt(r.amount) for r in self.refunds)
		if self.refunded_amount > flt(self.amount) + TOLERANCE:
			frappe.throw(_("Refunds cannot be more than the amount allocated."))
		self.outstanding_amount = flt(self.amount) - self.refunded_amount
		still_out = self.outstanding_amount > TOLERANCE
		self.base_outstanding_amount = flt(self.base_amount) - sum(flt(r.base_amount) for r in self.refunds) if still_out else 0
		if not still_out:
			self.status = "Refunded"
		elif self.refunded_amount:
			self.status = "Partly Refunded"
		elif self.status != AWAITING:
			self.status = "Outstanding"

	def on_cancel(self):
		if self.refunds:
			frappe.throw(_("Refunds have been recorded against this allocation; it cannot be cancelled."))
		if self.transfer_entry:
			if frappe.db.get_value("Payment Entry", self.transfer_entry, "docstatus") == 1:
				frappe.throw(_("The money has moved on {0}. Cancel that transfer first.").format(self.transfer_entry))
			frappe.delete_doc("Payment Entry", self.transfer_entry, ignore_permissions=True, force=True)
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def record_refund(
		self,
		amount: float,
		refund_date: str | None = None,
		reference: str | None = None,
		from_bank_account: str | None = None,
		to_bank_account: str | None = None,
		exchange_rate: float | None = None,
	):
		"""Finance records the money going back to the project it came from: it changes hands in the bank it comes from, and a
		draft transfer takes it on if the lending project wants it in another."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1:
			frappe.throw(_("Only an approved allocation can be refunded."))
		if self.status == AWAITING:
			frappe.throw(_("The money has not reached {0} yet. Submit the transfer first.").format(self.to_bank_account))
		amount = flt(amount)
		if amount <= 0 or amount > flt(self.outstanding_amount) + TOLERANCE:
			frappe.throw(_("The amount still to refund is {0}.").format(fmt_money(self.outstanding_amount, currency=self.currency)))
		if not (from_bank_account and to_bank_account):
			frappe.throw(_("Select the bank accounts the refund comes from and goes to."))
		on_date = refund_date or nowdate()
		home = _home(self.company)
		from_currency, to_currency = _currency_of(from_bank_account), _currency_of(to_bank_account)
		# with no change of currency nothing is exchanged, so it comes back at the rate it went out
		if from_currency == to_currency == self.currency:
			rate = flt(self.exchange_rate) or 1.0
		else:
			rate = _rate(self.company, exchange_rate, on_date, self.currency, from_currency, to_currency)
		bank_amount = _converted(amount, self.currency, from_currency, home, rate)
		held = funds.held(self.to_project, from_bank_account, self.company)
		if bank_amount > held + TOLERANCE:
			frappe.throw(
				_("{0} holds only {1} in {2}.").format(
					_project_name(self.to_project), fmt_money(held, currency=from_currency), from_bank_account
				),
				title=_("Not Enough Funds"),
			)
		row = self.append(
			"refunds",
			{
				"refund_date": on_date,
				"amount": amount,
				"reference": reference,
				"from_bank_account": from_bank_account,
				"to_bank_account": to_bank_account,
				"from_currency": from_currency,
				"to_currency": to_currency,
				"exchange_rate": rate,
				"base_amount": _converted(amount, self.currency, home, home, rate),
				"bank_amount": bank_amount,
				"received_amount": _converted(amount, self.currency, to_currency, home, rate),
			},
		)
		self.save()
		if from_bank_account != to_bank_account:
			self.raise_refund_transfer(row)
		managers = [project_manager_of(self.from_project), project_manager_of(self.to_project)]
		notify(
			[user for user in managers if user],
			_("{0} has refunded {1} to {2}; {3} is still to refund.").format(
				_project_name(self.to_project),
				fmt_money(amount, currency=self.currency),
				_project_name(self.from_project),
				fmt_money(self.outstanding_amount, currency=self.currency),
			),
			doc=self,
		)

	def raise_refund_transfer(self, row) -> str:
		transfer = _make_transfer(
			self, self.from_project, row.from_bank_account, row.to_bank_account, row.bank_amount, row.received_amount, row.exchange_rate, row.name
		)
		frappe.db.set_value("Resource Allocation Refund", row.name, "transfer_entry", transfer, update_modified=False)
		return transfer

	@frappe.whitelist()
	def raise_transfers(self) -> list:
		"""Draft transfers for what has to move and has none: one deleted or cancelled, or that could not be raised on approval."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1:
			frappe.throw(_("Only an approved allocation can be moved."))
		raised = []
		if self.moves_between_banks() and not self.transfer_entry:
			raised.append(self.raise_own_transfer())
		for row in self.refunds:
			if row.from_bank_account != row.to_bank_account and not row.transfer_entry:
				raised.append(self.raise_refund_transfer(row))
		return raised


def check_transfer(entry):
	"""A transfer raised here moves what was approved, between those banks: only its date, reference and rate can change."""
	name = entry.get("muhick_resource_allocation")
	if not name:
		return
	refund = entry.get("muhick_allocation_refund")
	if refund:
		approved = frappe.db.get_value("Resource Allocation Refund", refund, ["from_bank_account", "to_bank_account", "bank_amount"])
	else:
		approved = frappe.db.get_value("Resource Allocation", name, ["from_bank_account", "to_bank_account", "amount"])
	if approved and (entry.paid_from, entry.paid_to) == tuple(approved[:2]) and abs(flt(entry.paid_amount) - flt(approved[2])) <= TOLERANCE:
		return
	frappe.throw(_("This transfer must move what {0} approved, between the same bank accounts.").format(name), title=_("Internal Transfer"))


def on_transfer(entry, cancelled=False):
	"""Payment Entry submitted or cancelled: the allocation follows its transfer."""
	name = entry.get("muhick_resource_allocation")
	if not name:
		return
	refund = entry.get("muhick_allocation_refund")
	if refund:
		frappe.db.set_value("Resource Allocation Refund", refund, "transfer_entry", None if cancelled else entry.name, update_modified=False)
		return
	if cancelled and frappe.db.exists("Resource Allocation Refund", {"parent": name, "parenttype": "Resource Allocation"}):
		frappe.throw(_("Refunds have been recorded against {0}; its transfer cannot be cancelled.").format(name))
	frappe.db.set_value(
		"Resource Allocation",
		name,
		{"transfer_entry": None if cancelled else entry.name, "status": AWAITING if cancelled else "Outstanding"},
		update_modified=False,
	)
	if not cancelled:
		manager = project_manager_of(frappe.db.get_value("Resource Allocation", name, "to_project"))
		if manager:
			notify([manager], _("{0}: the money is now in {1}.").format(name, entry.paid_to), doc=frappe._dict(doctype="Resource Allocation", name=name))


def transfer_deleted(doc, method=None):
	"""A draft transfer deleted: it can be raised again."""
	name = doc.get("muhick_resource_allocation")
	if not name:
		return
	refund = doc.get("muhick_allocation_refund")
	if refund:
		frappe.db.set_value("Resource Allocation Refund", refund, "transfer_entry", None, update_modified=False)
	else:
		frappe.db.set_value("Resource Allocation", name, "transfer_entry", None, update_modified=False)


@frappe.whitelist()
def get_project_funds(company: str, projects) -> dict:
	"""What each project holds, bank by bank, for the form to show while the allocation is prepared."""
	frappe.has_permission("Resource Allocation", "read", throw=True)
	positions = funds.positions(company)
	projects = [project for project in frappe.parse_json(projects) if project]
	accounts = {
		account.name: account
		for account in frappe.get_all("Account", filters={"company": company}, fields=["name", "account_name", "account_currency"])
	}
	out = {}
	for project in projects:
		position = positions[project]
		held = [(account, amount) for account, amount in position.held.items() if abs(flt(amount)) > TOLERANCE]
		out[project] = {
			"name": _project_name(project),
			"available": flt(position.available),
			"banks": [
				{
					"account": account,
					"label": accounts[account].account_name if account in accounts else account,
					"currency": accounts[account].account_currency if account in accounts else None,
					"amount": flt(amount),
				}
				for account, amount in sorted(held, key=lambda pair: -flt(pair[1]))
			],
		}
	return out


@frappe.whitelist()
def get_bank_terms(
	company: str,
	from_bank_account: str | None = None,
	to_bank_account: str | None = None,
	on_date: str | None = None,
	currency: str | None = None,
) -> dict:
	"""What the form needs once a bank account is picked: each account's currency, and the rate where one is not the company's.
	Reading an account's currency here spares whoever prepares an allocation from needing the chart of accounts."""
	frappe.has_permission("Resource Allocation", "read", throw=True)
	home = _home(company)
	from_currency = _currency_of(from_bank_account) if from_bank_account else None
	to_currency = _currency_of(to_bank_account) if to_bank_account else from_currency
	on_the_document = {value for value in (from_currency, to_currency, currency) if value}
	foreign = on_the_document - {home}
	return {
		"currency": from_currency,
		"to_currency": to_currency,
		"company_currency": home,
		"exchange_rate": _market_rate(next(iter(foreign)), home, on_date or nowdate()) if len(foreign) == 1 else 1.0,
		"converts": len(on_the_document) > 1,
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def bank_account_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""The company's bank and cash accounts, for whoever prepares an allocation, who may not read the chart of accounts."""
	frappe.has_permission("Resource Allocation", "read", throw=True)
	return frappe.get_all(
		"Account",
		filters={"company": frappe._dict(filters or {}).company, "is_group": 0, "disabled": 0, "account_type": ("in", funds.BANK_AND_CASH)},
		or_filters={"name": ("like", f"%{txt}%"), "account_name": ("like", f"%{txt}%")},
		fields=["name", "account_name"],
		order_by="name",
		limit_start=start,
		limit_page_length=page_len,
		as_list=not as_dict,
	)
