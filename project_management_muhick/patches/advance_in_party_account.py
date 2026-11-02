# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Advances stay on the party's own account. The company setting that books them in a separate account goes off, and
draft payments it had already moved go back. Submitted payments have posted, and stay as they are."""

import frappe
from erpnext.accounts.party import get_party_account

SETTING = "book_advance_payments_in_separate_party_account"


def execute():
	frappe.db.set_value("Company", {SETTING: 1}, SETTING, 0)
	for entry in frappe.get_all(
		"Payment Entry",
		filters={"docstatus": 0, SETTING: 1, "party_type": ("in", ("Customer", "Supplier"))},
		fields=["name", "payment_type", "party_type", "party", "company"],
	):
		frappe.db.set_value(
			"Payment Entry",
			entry.name,
			{
				SETTING: 0,
				"paid_to" if entry.payment_type == "Pay" else "paid_from": get_party_account(entry.party_type, entry.party, entry.company),
			},
			update_modified=False,
		)
