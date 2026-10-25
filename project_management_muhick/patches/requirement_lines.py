# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Requirements and financial requirements are tables of lines now, on the lead and the opportunity.
Each line of the old text becomes a row, a bid security already recorded on an opportunity becomes a
Bid Security line (the amount is worked out from the lines now), and the old fields are removed."""

import frappe
from frappe.utils import flt

from project_management_muhick.setup.custom_fields import setup_custom_fields

# old text field -> new table, its row doctype, and the row made from one line of text
TEXT_TO_LINES = {
	"muhick_requirement": ("muhick_requirements", "Client Requirement", lambda line: {"requirement": line}),
	"muhick_financial_requirement": (
		"muhick_financial_requirements", "Financial Requirement", lambda line: {"requirement_type": "Other", "description": line[:140]},
	),
}
OLD_FIELDS = (
	"Lead-muhick_requirement", "Lead-muhick_financial_requirement", "Opportunity-muhick_requirement",
	"Opportunity-muhick_financial_requirement", "Opportunity-muhick_requirement_section",
)


def execute():
	setup_custom_fields()  # the new tables are normally added after patches run
	for doctype in ("Lead", "Opportunity"):
		for old, (table, child, make_row) in TEXT_TO_LINES.items():
			if not frappe.db.has_column(doctype, old):
				continue
			for name, text in frappe.db.sql(f"select name, `{old}` from `tab{doctype}` where ifnull(`{old}`, '') != ''"):
				add_lines(doctype, name, table, child, [make_row(line.strip()) for line in text.splitlines() if line.strip()])
	if frappe.db.has_column("Opportunity", "muhick_bid_security_amount"):
		for o in frappe.get_all("Opportunity", filters={"muhick_bid_security_required": 1}, fields=["name", "muhick_bid_security_amount"]):
			if not frappe.db.exists("Financial Requirement", {"parent": o.name, "parenttype": "Opportunity", "requirement_type": "Bid Security"}):
				add_lines(
					"Opportunity", o.name, "muhick_financial_requirements", "Financial Requirement",
					[{"requirement_type": "Bid Security", "amount": flt(o.muhick_bid_security_amount)}],
				)
	for name in OLD_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


def add_lines(doctype, name, table, child, rows):
	start = frappe.db.count(child, {"parent": name, "parenttype": doctype, "parentfield": table})
	for idx, row in enumerate(rows, start + 1):
		frappe.get_doc({"doctype": child, "parent": name, "parenttype": doctype, "parentfield": table, "idx": idx, **row}).db_insert()
