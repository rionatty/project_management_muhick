# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Roles, suggested role profiles and the few permissions added to standard documents."""

import frappe

from project_management_muhick.utils.common import COO, FM, FO, GM, PM, PRM, PRO, SE, SK, SSK

ADMIN_MANAGER = "Administration Manager"
HEAD_OF_SALES = "Head of Sales"
FLEET_OFFICER = "Fleet Officer"
ROLES = [PM, COO, FM, GM, FO, PRM, PRO, SK, SSK, SE, ADMIN_MANAGER, HEAD_OF_SALES, FLEET_OFFICER]

# Muhick job roles bundled with the standard ERPNext roles each one needs.
# Receipt, supplier invoice and payment sit in different profiles on purpose.
ROLE_PROFILES = {
	"Muhick Project Manager": [PM, "Projects Manager", "Projects User"],
	"Muhick Chief Operating Officer": [COO, "Projects Manager", "Projects User"],
	"Muhick Finance Manager": [FM, "Accounts Manager", "Accounts User"],
	"Muhick Finance Officer": [FO, "Accounts User"],
	"Muhick General Manager": [GM, "Projects User"],
	# the supplier and item lists are theirs: nobody else creates a supplier or changes an item
	"Muhick Procurement Manager": [PRM, "Purchase Manager", "Purchase Master Manager", "Purchase User", "Stock User", "Item Manager"],
	"Muhick Procurement Officer": [PRO, "Purchase User", "Stock User"],
	"Muhick Storekeeper": [SK, "Stock User"],
	"Muhick Site Storekeeper": [SSK, "Stock User"],
	"Muhick Sales Engineer": [SE, "Sales User"],
	"Muhick Administration Manager": [ADMIN_MANAGER, "Stock User"],
	"Muhick Head of Sales": [HEAD_OF_SALES, SE, "Sales Manager", "Sales User"],
	"Muhick Fleet Officer": [FLEET_OFFICER],
}

READ = ("read", "print", "email", "report")
RAISE = (*READ, "write", "create", "share")
SUBMIT = (*RAISE, "submit")
APPROVE = (*READ, "write", "submit", "cancel")

# permissions the approval flows need on standard documents, beyond the standard ERPNext roles
STANDARD_DOCTYPE_PERMISSIONS = {
	"Material Request": {
		PM: RAISE, SK: RAISE, SSK: RAISE, ADMIN_MANAGER: RAISE, COO: APPROVE, FM: APPROVE, GM: APPROVE, PRM: APPROVE,
	},
	# the officer issues the request and so sends it; the standard purchase role can only draft it
	"Request for Quotation": {PRO: SUBMIT, ADMIN_MANAGER: SUBMIT},
	# sales engineers read the quotations that price a bid's BOQ and name the supplier of each line of a cost estimate;
	# the General Manager reads them too, and decides the supplier of an administration purchase
	"Supplier Quotation": {PRO: RAISE, PRM: APPROVE, SE: READ, GM: APPROVE, ADMIN_MANAGER: RAISE},
	"Supplier": {SE: READ},
	# Project Managers are added to this by Muhick Settings when they are allowed to see supplier prices
	"Purchase Order": {PRO: RAISE, PRM: RAISE, FM: APPROVE, GM: APPROVE, COO: READ, FO: READ, ADMIN_MANAGER: SUBMIT},
	"Payment Request": {PRO: RAISE, PRM: (*SUBMIT, "cancel"), FM: (*SUBMIT, "cancel"), FO: SUBMIT, GM: READ, ADMIN_MANAGER: SUBMIT},
	# what the Administration Manager picks on those forms, as a purchase role would
	"Purchase Taxes and Charges Template": {ADMIN_MANAGER: READ},
	"Price List": {ADMIN_MANAGER: READ},
	"Mode of Payment": {ADMIN_MANAGER: READ},
	"Cost Center": {ADMIN_MANAGER: READ},
	"Vehicle": {ADMIN_MANAGER: RAISE, FLEET_OFFICER: READ, FM: READ, FO: READ},
	"Purchase Receipt": {SK: RAISE, SSK: RAISE, PRM: APPROVE, FM: READ, FO: READ, PM: READ, ADMIN_MANAGER: SUBMIT},
	# Finance adds the landed cost of an import to the goods
	"Landed Cost Voucher": {FM: (*SUBMIT, "cancel"), FO: SUBMIT},
	"Delivery Note": {SK: RAISE, PRM: APPROVE, FM: APPROVE, FO: APPROVE},
	# most stock entries are submitted directly by the storekeeper
	"Stock Entry": {SK: SUBMIT, SSK: SUBMIT, PRM: APPROVE, FM: APPROVE, FO: APPROVE, PM: READ},
	"Project": {GM: READ, FM: READ, FO: READ, PRM: READ, PRO: READ, SK: READ, SSK: READ, SE: READ},
	"Task": {GM: READ, FM: READ, PRM: READ, PRO: READ, SSK: READ},
	# the shared milestone list; Project Managers and the COO maintain it through Projects Manager
	"Task Type": {SE: READ, GM: READ, FM: READ, FO: READ, PRM: READ, PRO: READ},
	# the Sector and Sales Stage lists; the Head of Sales maintains them as Sales Manager
	"Market Segment": {SE: READ},
	"Sales Stage": {SE: READ},
	# bids are opportunities: management, finance, projects and procurement (who ask suppliers to price
	# them) follow them
	"Opportunity": {GM: READ, COO: READ, FM: READ, FO: READ, PM: READ, PRM: READ, PRO: READ},
}


# a report's own list of roles replaces the standard one, so it names those too
REPORT_ROLES = {
	# the General Manager decides the supplier of an administration purchase from this comparison
	"Supplier Quotation Comparison": (GM, "Purchase Manager", "Purchase User", "Stock User", "Manufacturing Manager"),
}


def setup_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc(doctype="Role", role_name=role, desk_access=1, is_custom=1).insert(ignore_permissions=True)


def setup_role_profiles():
	for profile, roles in ROLE_PROFILES.items():
		if frappe.db.exists("Role Profile", profile):
			continue
		roles = [r for r in roles if frappe.db.exists("Role", r)]
		frappe.get_doc(
			doctype="Role Profile", role_profile=profile, roles=[{"role": r} for r in roles]
		).insert(ignore_permissions=True)


def setup_standard_permissions():
	from frappe.permissions import add_permission, update_permission_property

	for doctype, role_perms in STANDARD_DOCTYPE_PERMISSIONS.items():
		for role, ptypes in role_perms.items():
			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
				continue
			add_permission(doctype, role, 0)
			for ptype in ptypes:
				if ptype != "read":
					update_permission_property(doctype, role, 0, ptype, 1, validate=False)


def setup_report_roles():
	for report, roles in REPORT_ROLES.items():
		if frappe.db.exists("Custom Role", {"report": report}) or not frappe.db.exists("Report", report):
			continue
		frappe.get_doc(
			doctype="Custom Role", report=report, roles=[{"role": role} for role in roles if frappe.db.exists("Role", role)]
		).insert(ignore_permissions=True)


def restrict_bank_details():
	"""Bank details belong to the Finance Manager (Accounts Manager): whoever makes the payments reads them
	and does not change them. Run once, so a site can decide otherwise afterwards."""
	from frappe.permissions import update_permission_property

	for ptype in ("create", "write", "delete"):
		update_permission_property("Bank Account", "Accounts User", 0, ptype, 0, validate=False)
	frappe.clear_cache(doctype="Bank Account")


def apply_price_visibility(show: bool):
	"""Let Project Managers open Purchase Orders, or not. Supplier prices sit on the order, so
	leaving this off keeps them from the operations team."""
	from frappe.permissions import add_permission, update_permission_property

	existing = frappe.db.get_value("Custom DocPerm", {"parent": "Purchase Order", "role": PM, "permlevel": 0}, "name")
	if show and not existing:
		add_permission("Purchase Order", PM, 0)
		for ptype in READ:
			if ptype != "read":
				update_permission_property("Purchase Order", PM, 0, ptype, 1, validate=False)
	elif not show and existing:
		frappe.delete_doc("Custom DocPerm", existing, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype="Purchase Order")
