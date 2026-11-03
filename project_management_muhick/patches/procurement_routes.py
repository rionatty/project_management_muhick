# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The administration route through procurement, and what an import order needs. The General Manager, who only read
quotations, now decides the supplier of an administration purchase. An order already raised takes its type of procurement
from its requisition, so its invoices can be told apart."""

import frappe
from frappe.permissions import update_permission_property

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.workflows import setup_workflows
from project_management_muhick.utils.common import GM


def execute():
	setup_custom_fields()
	for ptype in ("write", "submit", "cancel"):
		update_permission_property("Supplier Quotation", GM, 0, ptype, 1, validate=False)
	for order in frappe.get_all(
		"Purchase Order", filters={"muhick_procurement_requisition": ("is", "set")}, fields=["name", "muhick_procurement_requisition"]
	):
		kind = frappe.db.get_value("Procurement Requisition", order.muhick_procurement_requisition, "procurement_type")
		frappe.db.set_value("Purchase Order", order.name, "muhick_procurement_type", kind, update_modified=False)
	setup_workflows(
		force=True, doctypes=["Supplier Quotation", "Procurement Requisition", "Purchase Order", "Purchase Receipt", "Payment Request"]
	)
