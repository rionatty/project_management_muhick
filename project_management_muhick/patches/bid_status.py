# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The bid status: an opportunity's sales stage moves by itself with what is recorded on the bid, from
Qualified to Won, Lost, Not Pursued or Cancelled. "Awarded" becomes "Won", the standard "Replied"
status is no longer used, every bid's status is worked out from what it holds, and a won bid's costs
go to its project under a cost code of their own."""

import frappe
from frappe.utils import getdate

from project_management_muhick.overrides.crm import bid_status
from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import COST_CODES, setup_crm_lists

BID_COST_CODE = "ADM-600"


def execute():
	if frappe.db.exists("Sales Stage", "Awarded"):
		merge = bool(frappe.db.exists("Sales Stage", "Won"))
		frappe.rename_doc("Sales Stage", "Awarded", "Won", force=True, merge=merge, show_alert=False)
	setup_custom_fields()  # the new fields are normally added after patches run
	setup_crm_lists()
	frappe.db.sql("update `tabOpportunity` set status = 'Open' where status = 'Replied'")
	for code, name, section, category in COST_CODES:
		if code == BID_COST_CODE and not frappe.db.exists("Cost Code", code):
			frappe.get_doc(
				doctype="Cost Code", cost_code=code, cost_code_name=name, budget_section=section, cost_category=category
			).insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Muhick Settings", "bid_cost_code") and frappe.db.exists("Cost Code", BID_COST_CODE):
		frappe.db.set_single_value("Muhick Settings", "bid_cost_code", BID_COST_CODE)
	for name in frappe.get_all("Opportunity", pluck="name"):
		doc = frappe.get_doc("Opportunity", name)
		frappe.db.set_value(
			"Opportunity", name, {"sales_stage": bid_status(doc), "muhick_stage_since": getdate(doc.modified)}, update_modified=False
		)
