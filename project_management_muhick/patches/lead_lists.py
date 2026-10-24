# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads and bids share ERPNext's Source list (UTM Source) now, and leads have a Sector list
(Market Segment). Creates both lists, moves a bid's source to its new name, and keeps any other
source already used on a bid."""

import frappe

from project_management_muhick.setup.defaults import setup_lead_lists

RENAMED = {
	"Government Procurement Portal": "e-GP Portal",
	"Newspaper": "Newspaper Advert",
	"Website": "Website Advert",
	"Existing Client": "Existing Customer",
}


def execute():
	setup_lead_lists()
	for old, new in RENAMED.items():
		frappe.db.set_value("Bid", {"lead_source": old}, "lead_source", new, update_modified=False)
	for name in set(frappe.get_all("Bid", filters={"lead_source": ("is", "set")}, pluck="lead_source")):
		if not frappe.db.exists("UTM Source", name):
			frappe.get_doc(doctype="UTM Source").insert(set_name=name, ignore_permissions=True)
