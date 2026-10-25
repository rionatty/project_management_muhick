# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bid documents become documents of their own. The opportunity's table of them is taken off before the
document changes, or it would point at a document that is no longer a table; its lines stay and become
documents once the change is made."""

import frappe


def execute():
	if frappe.db.exists("Custom Field", "Opportunity-muhick_documents"):
		frappe.delete_doc("Custom Field", "Opportunity-muhick_documents", ignore_permissions=True, force=True)
