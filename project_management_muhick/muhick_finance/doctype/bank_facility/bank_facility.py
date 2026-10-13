# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A facility agreed with a bank and its limit. What is in use is the total of the instruments
still running against it (letters of credit, bid securities, bonds, guarantees), so the limit,
the amount running and the balance are always known."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

RUNNING = ("Requested", "Active", "Cancellation Requested")


class BankFacility(Document):
	def validate(self):
		if flt(self.limit_amount) <= 0:
			frappe.throw(_("Enter the facility limit."))
		self.utilised = get_utilised(self.name) if not self.is_new() else 0
		self.available = flt(self.limit_amount) - flt(self.utilised)


def get_utilised(facility, exclude=None) -> float:
	amounts = frappe.get_all(
		"Bank Instrument",
		filters={"bank_facility": facility, "status": ("in", RUNNING), "name": ("!=", exclude or "")},
		pluck="amount",
	)
	return sum(flt(a) for a in amounts)


def update_utilisation(facility):
	if not facility or not frappe.db.exists("Bank Facility", facility):
		return
	utilised = get_utilised(facility)
	limit = flt(frappe.db.get_value("Bank Facility", facility, "limit_amount"))
	frappe.db.set_value("Bank Facility", facility, {"utilised": utilised, "available": limit - utilised}, update_modified=False)
