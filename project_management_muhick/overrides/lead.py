# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads: whether to pursue one is the Head of Sales' decision, recorded with who made it and when."""

import frappe
from frappe import _
from frappe.utils import today

DECIDED = ("Qualified", "Not Pursued")
DECIDERS = {"Head of Sales", "Sales Manager"}


def validate(doc, method=None):
	if not doc.has_value_changed("qualification_status"):
		return
	before = doc.get_doc_before_save()
	deciding = doc.qualification_status in DECIDED or (before and before.qualification_status in DECIDED)
	if deciding and not DECIDERS & set(frappe.get_roles()):
		frappe.throw(_("Only the Head of Sales decides whether a lead is pursued."))
	if doc.qualification_status in DECIDED:
		doc.qualified_by, doc.qualified_on = frappe.session.user, today()
	else:
		doc.qualified_by = doc.qualified_on = None
