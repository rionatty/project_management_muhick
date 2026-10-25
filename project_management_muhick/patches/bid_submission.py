# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid's documents are a table now and its submission has a record of its own. The single
attachment becomes a document line, the submission date becomes the submission date and time, and the
old fields are removed."""

import frappe
from frappe.utils import get_datetime

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_crm_lists


def execute():
	setup_custom_fields()  # the new fields are normally added after patches run
	setup_crm_lists()
	if frappe.db.has_column("Opportunity", "muhick_submitted_on"):
		for name, submitted in frappe.db.sql(
			"select name, muhick_submitted_on from `tabOpportunity` where muhick_submitted_on is not null and muhick_submitted_at is null"
		):
			frappe.db.set_value("Opportunity", name, "muhick_submitted_at", get_datetime(submitted), update_modified=False)
	if frappe.db.has_column("Opportunity", "muhick_bid_documents"):
		for name, url in frappe.db.sql("select name, muhick_bid_documents from `tabOpportunity` where ifnull(muhick_bid_documents, '') != ''"):
			if not frappe.db.exists("Bid Document", {"parent": name, "parenttype": "Opportunity"}):
				frappe.get_doc(
					{
						"doctype": "Bid Document", "parent": name, "parenttype": "Opportunity", "parentfield": "muhick_documents",
						"idx": 1, "document_type": "Other", "part": "Administrative", "file": url,
					}
				).db_insert()
	for field in ("Opportunity-muhick_submitted_on", "Opportunity-muhick_bid_documents", "Opportunity-muhick_preparation_column_2"):
		if frappe.db.exists("Custom Field", field):
			frappe.delete_doc("Custom Field", field, ignore_permissions=True, force=True)
