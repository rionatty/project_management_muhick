# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""What the client's review asked of approvals and master data. The limits now reach the procurement
requisition and the purchase order, and the order goes to the Finance Manager before the General Manager;
only the Finance Manager changes bank details; the Procurement Manager holds the item list."""

import frappe
from frappe.permissions import add_permission, update_permission_property

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.roles import APPROVE, restrict_bank_details
from project_management_muhick.setup.workflows import setup_workflows
from project_management_muhick.utils.common import FM

ITEM_OWNER = "Muhick Procurement Manager"


def execute():
	setup_custom_fields()
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
