# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_defaults
from project_management_muhick.setup.roles import setup_role_profiles, setup_roles, setup_standard_permissions
from project_management_muhick.setup.workflows import setup_workflows

# ERPNext's own desk icon for its Projects workspace
STANDARD_PROJECTS_ICON = "Projects"

# ERPNext's CRM menu, where the sales team works, also lists the sales requisitions, bid security
# requests and outcome reports, the bid register and the margin comparison: (placed after the item
# linking to, label, link type, link to, inside a section)
CRM_SIDEBAR = "CRM"
CRM_ITEMS = (
	("Opportunity", "Sales Requisition", "DocType", "Sales Requisition", 0),
	("Sales Requisition", "Bid Security Request", "DocType", "Bid Security Request", 0),
	("Bid Security Request", "Bid Outcome", "DocType", "Bid Outcome", 0),
	("Opportunity Summary by Sales Stage", "Bid Register", "Report", "Bid Register", 1),
	("Bid Register", "Bid Margin Comparison", "Report", "Bid Margin Comparison", 1),
	# the sales team's own lists, in the menu's Setup section
	("Sales Stage", "Opportunity Milestones", "DocType", "Opportunity Milestone", 1),
	("Opportunity Milestone", "Bid Document Types", "DocType", "Bid Document Type", 1),
	("Bid Document Type", "Financial Requirement Types", "DocType", "Financial Requirement Type", 1),
)
# taken out of the CRM menu while the app is installed (a lead is already one organisation), put back
# on uninstall
CRM_HIDDEN = (("Contact", "Prospect", "DocType", "Prospect", 1),)


def after_install():
	setup()
	setup_defaults()


def after_migrate():
	setup()


def before_uninstall():
	show_standard_projects_icon(True)
	if frappe.db.exists("Workspace Sidebar", CRM_SIDEBAR):
		frappe.db.delete("Workspace Sidebar Item", {"parent": CRM_SIDEBAR, "link_to": ("in", [i[3] for i in CRM_ITEMS])})
		for item in CRM_HIDDEN:
			add_crm_item(*item)


def setup():
	"""Safe to run any number of times: creates what is missing and leaves the rest alone."""
	setup_roles()
	setup_custom_fields()
	setup_role_profiles()
	setup_standard_permissions()
	setup_workflows()
	show_standard_projects_icon(False)
	add_sales_to_crm_menu()
	frappe.clear_cache()


def show_standard_projects_icon(show):
	"""One projects icon on the desk. This app's sidebar carries everything ERPNext's Projects
	workspace has (timesheets, activity types, project types, settings and its reports), so
	ERPNext's Projects icon is hidden while the app is installed and shown again on uninstall."""
	hidden = 0 if show else 1
	if frappe.db.exists("Desktop Icon", STANDARD_PROJECTS_ICON):
		if frappe.db.get_value("Desktop Icon", STANDARD_PROJECTS_ICON, "hidden") != hidden:
			frappe.db.set_value("Desktop Icon", STANDARD_PROJECTS_ICON, "hidden", hidden)


def add_sales_to_crm_menu():
	"""Put back after every migrate, since ERPNext rewrites its menu when it updates it. The rows go
	straight into the table: saving ERPNext's menu would also write it into ERPNext's files on a
	developer site."""
	if not frappe.db.exists("Workspace Sidebar", CRM_SIDEBAR):
		return
	# bids, and then their documents, used to be separate documents
	frappe.db.delete(
		"Workspace Sidebar Item", {"parent": CRM_SIDEBAR, "link_to": ("in", ["Bid", "Bid Document", *(i[3] for i in CRM_HIDDEN)])}
	)
	for item in CRM_ITEMS:
		add_crm_item(*item)


def add_crm_item(after, label, link_type, link_to, child):
	items = frappe.get_all(
		"Workspace Sidebar Item",
		filters={"parent": CRM_SIDEBAR, "parenttype": "Workspace Sidebar"},
		fields=["name", "idx", "link_to"],
		order_by="idx asc",
	)
	if any(i.link_to == link_to for i in items):
		return
	anchor = next((i for i in items if i.link_to == after), None)
	idx = anchor.idx + 1 if anchor else len(items) + 1
	for i in items:
		if i.idx >= idx:
			frappe.db.set_value("Workspace Sidebar Item", i.name, "idx", i.idx + 1, update_modified=False)
	frappe.get_doc(
		{
			"doctype": "Workspace Sidebar Item",
			"parent": CRM_SIDEBAR,
			"parenttype": "Workspace Sidebar",
			"parentfield": "items",
			"idx": idx,
			"type": "Link",
			"label": label,
			"link_type": link_type,
			"link_to": link_to,
			"child": child,
		}
	).db_insert()
