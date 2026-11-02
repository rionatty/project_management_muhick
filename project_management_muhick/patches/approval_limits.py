# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""What the client's review asked of approvals and master data. The limits now reach the procurement
requisition and the purchase order, and the order goes to the Finance Manager before the General Manager;
a requisition's prices are read in the company's currency; only the Finance Manager changes bank details;
the Procurement Manager holds the item list."""

import frappe
from frappe.permissions import add_permission, update_permission_property

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.roles import APPROVE, restrict_bank_details
from project_management_muhick.setup.workflows import setup_workflows
from project_management_muhick.utils.common import FM

ITEM_OWNER = "Muhick Procurement Manager"


def execute():
	setup_custom_fields()
	for requisition in frappe.get_all("Procurement Requisition", fields=["name", "supplier_quotation", "total_amount"]):
		currency, rate = frappe.db.get_value("Supplier Quotation", requisition.supplier_quotation, ["currency", "conversion_rate"]) or (None, 1)
		frappe.db.set_value(
			"Procurement Requisition",
			requisition.name,
			{"currency": currency, "conversion_rate": rate or 1, "base_total_amount": (requisition.total_amount or 0) * (rate or 1)},
			update_modified=False,
		)
	frappe.db.set_single_value(
		"Muhick Settings", {"high_risk_single_quotation": 1, "high_risk_advance_payment": 1, "high_risk_international": 1}
	)
	setup_workflows(force=True, doctypes=["Procurement Requisition", "Purchase Order"])
	if not frappe.db.exists("Custom DocPerm", {"parent": "Purchase Order", "role": FM, "permlevel": 0}):
		add_permission("Purchase Order", FM, 0)
	for ptype in APPROVE:
		if ptype != "read":
			update_permission_property("Purchase Order", FM, 0, ptype, 1, validate=False)
	frappe.clear_cache(doctype="Purchase Order")
	restrict_bank_details()
	if frappe.db.exists("Role Profile", ITEM_OWNER):
		profile = frappe.get_doc("Role Profile", ITEM_OWNER)
		if not any(row.role == "Item Manager" for row in profile.roles):
			profile.append("roles", {"role": "Item Manager"})
			profile.save(ignore_permissions=True)
