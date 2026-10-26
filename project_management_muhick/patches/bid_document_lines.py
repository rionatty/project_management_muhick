# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bid documents are tracked on the lines of the opportunity's document checklist: each line holds the
document's status, who prepares it, by when, how long it is valid, its file and remarks. The documents
kept on their own until now (or, on older sites, in the opportunity's table of documents) are moved onto
their lines, and every line gets its status, who prepares it and by when."""

import frappe
from frappe.utils import getdate

from project_management_muhick.overrides.crm import BID_PARTS, refresh_bid_status, set_parts_ready
from project_management_muhick.setup.custom_fields import setup_custom_fields

TRACKED = ("status", "prepared_by", "due_date", "valid_until", "remarks")
STATUSES = ("Pending", "In Progress", "Ready")


def execute():
	setup_custom_fields()  # the checklist's description is normally updated after patches run
	move_documents()
	for name in frappe.get_all("Opportunity", pluck="name"):
		fill_lines(name)
		refresh_bid_status(name)


def move_documents():
	if not frappe.db.table_exists("Bid Document"):
		return
	have = set(frappe.db.get_table_columns("Bid Document"))
	columns = ["name", "parent", "parenttype", "document_type", "file"] + [c for c in ("opportunity", *TRACKED) if c in have]
	linked = "bid_document" in set(frappe.db.get_table_columns("Bid Checklist Item"))
	parts = dict(frappe.get_all("Bid Document Type", fields=["name", "part"], as_list=True))
	documents = frappe.db.sql("select {} from `tabBid Document`".format(", ".join(f"`{c}`" for c in columns)), as_dict=True)
	for d in documents:
		opportunity = d.get("opportunity") or (d.parent if d.parenttype == "Opportunity" else None)
		if not (opportunity and d.document_type and frappe.db.exists("Opportunity", opportunity)):
			continue
		values = {f: d.get(f) for f in TRACKED if d.get(f)}
		values.update({"file": d.file, "part": parts.get(d.document_type)})
		if values.get("status") not in STATUSES:
			values["status"] = "Ready" if d.file else "Pending"
		on = {"parent": opportunity, "parenttype": "Opportunity", "parentfield": "muhick_checklist"}
		# the line it was tracked from, or a line of its type with no file yet, or a new line
		tracked = frappe.db.sql(
			"select name from `tabBid Checklist Item` where bid_document = %s and parent = %s", (d.name, opportunity)
		) if linked else None
		line = tracked[0][0] if tracked else frappe.db.get_value(
			"Bid Checklist Item", {**on, "document_type": d.document_type, "file": ("is", "not set")}, "name", order_by="idx asc"
		)
		if line:
			frappe.db.set_value("Bid Checklist Item", line, values, update_modified=False)
			continue
		last = frappe.db.sql(
			"select max(idx) from `tabBid Checklist Item` where parent = %s and parenttype = 'Opportunity'", opportunity
		)[0][0]
		frappe.get_doc(
			{"doctype": "Bid Checklist Item", **on, "idx": (last or 0) + 1, "document_type": d.document_type, **values}
		).db_insert()


def fill_lines(name):
	"""Every line with a status (one with no document yet is Pending), who prepares it and by when; then
	the parts that are ready."""
	doc = frappe.get_doc("Opportunity", name)
	deadline = doc.get("muhick_submission_deadline")
	parts = dict(frappe.get_all("Bid Document Type", fields=["name", "part"], as_list=True))
	for row in doc.get("muhick_checklist"):
		values = {}
		if row.status not in STATUSES:
			values["status"] = "Ready" if row.file else "Pending"
		if not row.prepared_by and doc.opportunity_owner:
			values["prepared_by"] = doc.opportunity_owner
		if not row.due_date and deadline:
			values["due_date"] = getdate(deadline)
		if not row.part and parts.get(row.document_type):
			values["part"] = parts[row.document_type]
		if values:
			frappe.db.set_value("Bid Checklist Item", row.name, values, update_modified=False)
			row.update(values)
	set_parts_ready(doc)
	frappe.db.set_value("Opportunity", name, {field: doc.get(field) for field, _part in BID_PARTS}, update_modified=False)
