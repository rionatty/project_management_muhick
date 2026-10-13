# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Segregation of duties on the purchase cycle.

Supplier creation, goods receipt, invoice posting and payment should not sit with one user.
The action (Off / Warn / Block) is set in Muhick Settings.
"""

import frappe
from frappe import _

from project_management_muhick.utils.common import get_settings


def _act(violations):
	if not violations:
		return
	action = get_settings().segregation_of_duties_action or "Warn"
	if action == "Off":
		return
	message = _("Segregation of duties:") + "<br>" + "<br>".join(violations)
	if action == "Block":
		frappe.throw(message, title=_("Segregation of Duties"))
	frappe.msgprint(message, title=_("Segregation of Duties"), indicator="orange")


def _exempt(user) -> bool:
	return user == "Administrator" or (get_settings().segregation_of_duties_action or "Warn") == "Off"


def check_purchase_invoice(doc):
	"""The person posting the supplier invoice should not be the one who received the goods."""
	user = frappe.session.user
	if _exempt(user) or doc.is_return:
		return
	receipts = {row.purchase_receipt for row in doc.items if row.get("purchase_receipt")}
	if not receipts:
		return
	mine = frappe.get_all("Purchase Receipt", filters={"name": ("in", list(receipts)), "owner": user}, pluck="name")
	_act([_("You received the goods on {0} and are also posting the supplier invoice.").format(name) for name in mine])


def check_payment_entry(doc):
	"""The person paying should not have posted the invoice, received the goods or created the supplier."""
	user = frappe.session.user
	if _exempt(user) or doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	violations = []
	if doc.party and frappe.db.get_value("Supplier", doc.party, "owner") == user:
		violations.append(_("You created supplier {0} and are also paying it.").format(doc.party))
	invoices = [r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Purchase Invoice"]
	for name in frappe.get_all("Purchase Invoice", filters={"name": ("in", invoices), "owner": user}, pluck="name") if invoices else []:
		violations.append(_("You posted supplier invoice {0} and are also paying it.").format(name))
	if invoices:
		receipts = frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": ("in", invoices), "purchase_receipt": ("is", "set")},
			pluck="purchase_receipt",
			distinct=True,
		)
		if receipts:
			for name in frappe.get_all("Purchase Receipt", filters={"name": ("in", receipts), "owner": user}, pluck="name"):
				violations.append(_("You received the goods on {0} and are also paying for them.").format(name))
	_act(violations)
