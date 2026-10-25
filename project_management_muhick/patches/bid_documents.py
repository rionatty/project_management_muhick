# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Each bid document is a document of its own now, and every bid has a document checklist. The lines of
the opportunity's old table become documents (ready when they have their file), the document types
every bid needs are marked, each bid's checklist is drawn up (a bid still being prepared starts with
those types, and its bid security if it has one), and its parts and status follow."""

import frappe
from frappe.utils import getdate

from project_management_muhick.overrides.crm import (
	BID_PARTS, add_bid_security, apply_documents, bid_status, default_checklist, documents_of, set_parts_ready,
)
from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import BID_DOCUMENT_TYPES, setup_crm_lists


def execute():
	setup_custom_fields()  # the checklist is normally added after patches run
	setup_crm_lists()
	for name, _part, every in BID_DOCUMENT_TYPES:
		if every and frappe.db.exists("Bid Document Type", name):
			frappe.db.set_value("Bid Document Type", name, "in_every_bid", 1, update_modified=False)
	for row in frappe.db.sql(
		"select name, parent, file from `tabBid Document` where parenttype = 'Opportunity' and ifnull(opportunity, '') = ''",
		as_dict=True,
	):
		bid = frappe.db.get_value(
			"Opportunity", row.parent, ["customer_name", "opportunity_owner", "muhick_submission_deadline"], as_dict=True
		)
		if not bid:
			continue
		deadline = bid.muhick_submission_deadline
		frappe.db.set_value(
			"Bid Document",
			row.name,
			{
				"opportunity": row.parent,
				"organisation": bid.customer_name,
				"status": "Ready" if row.file else "Pending",
				"prepared_by": bid.opportunity_owner,
				"due_date": getdate(deadline) if deadline else None,
				"naming_series": "BDOC-.YYYY.-.#####",
				"parent": None,
				"parenttype": None,
				"parentfield": None,
			},
			update_modified=False,
		)
	for name in frappe.get_all("Opportunity", pluck="name"):
		doc = frappe.get_doc("Opportunity", name)
		stored = {row.name for row in doc.get("muhick_checklist")}
		if doc.sales_stage in ("Qualified", "In Preparation"):
			if not stored:
				default_checklist(doc)
			add_bid_security(doc)
		apply_documents(doc, documents_of(doc))
		set_parts_ready(doc)
		for row in doc.get("muhick_checklist"):
			if row.name in stored:
				row.db_update()
			else:
				row.db_insert()
		values = {field: doc.get(field) for field, _part in BID_PARTS}
		values["sales_stage"] = bid_status(doc)
		frappe.db.set_value("Opportunity", name, values, update_modified=False)
