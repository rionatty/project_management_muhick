# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads and bids share ERPNext's Source list (UTM Source) now, and leads have a Sector list
(Market Segment). Creates both lists, moves a bid's source to its new name, and keeps any other
source already used on a bid."""

import frappe

from project_management_muhick.setup.defaults import setup_crm_lists

RENAMED = {
	"Government Procurement Portal": "e-GP Portal",
	"Newspaper": "Newspaper Advert",
	"Website": "Website Advert",
	"Existing Client": "Existing Customer",
}


def execute():
	setup_crm_lists()
	# bids are opportunities now; a site that has not run this yet still has the old table
	if not frappe.db.table_exists("Bid"):
		return
	for old, new in RENAMED.items():
		frappe.db.sql("update `tabBid` set lead_source = %s where lead_source = %s", (new, old))
	for (name,) in frappe.db.sql("select distinct lead_source from `tabBid` where ifnull(lead_source, '') != ''"):
		if not frappe.db.exists("UTM Source", name):
			frappe.get_doc(doctype="UTM Source").insert(set_name=name, ignore_permissions=True)
