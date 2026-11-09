# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Suppliers are now chosen on a Supplier Evaluation, approved once, so a quotation no longer goes for approval on its own and
needs no justification of its own. A quotation approved before this keeps every line chosen, as its approval chose them."""

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.workflows import workflow_name


def execute():
	setup_custom_fields()
	name = workflow_name("Supplier Quotation")
	if frappe.db.exists("Workflow", name):
		frappe.delete_doc("Workflow", name, ignore_permissions=True, force=True)
	frappe.db.sql(
		"""
		update `tabSupplier Quotation Item` i inner join `tabSupplier Quotation` q on q.name = i.parent
		set i.muhick_selected = 1
		where q.docstatus = 1
		"""
	)
	if frappe.db.exists("Custom Field", "Supplier Quotation-muhick_justification"):
		frappe.delete_doc("Custom Field", "Supplier Quotation-muhick_justification", ignore_permissions=True, force=True)
