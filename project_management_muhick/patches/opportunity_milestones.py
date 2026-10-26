# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The milestones belong to the opportunity: they run from the lead to the project and sit on its first
tab with its progress. The Bid Milestones list becomes the Opportunity Milestones list (milestones the
business added are kept), and every opportunity's milestones are drawn up again."""

import frappe

from project_management_muhick.overrides.crm import refresh_bid_status
from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_crm_lists

# the first list, replaced by the new defaults
FIRST_LIST = (
	"Lead Qualified", "Bid Funds Issued", "Site Visit Done", "Bid Security Issued", "Administrative Bid Ready",
	"Technical Bid Ready", "Financial Bid Ready", "Bid Submitted", "Outcome Approved",
)
RENAMED_RULES = {"Bid Opened": "Opportunity Opened"}


def execute():
	if frappe.db.exists("Custom Field", "Opportunity-muhick_bid_progress"):
		frappe.delete_doc("Custom Field", "Opportunity-muhick_bid_progress", ignore_permissions=True, force=True)
	setup_custom_fields()  # the new fields are normally added after patches run
	setup_crm_lists()
	if frappe.db.table_exists("Bid Milestone"):
		for m in frappe.db.sql(
			"select milestone_name, weight, reached_when, sequence, disabled from `tabBid Milestone`", as_dict=True
		):
			if m.milestone_name in FIRST_LIST or frappe.db.exists("Opportunity Milestone", m.milestone_name):
				continue
			frappe.get_doc(
				doctype="Opportunity Milestone",
				milestone_name=m.milestone_name,
				weight=m.weight,
				reached_when=RENAMED_RULES.get(m.reached_when, m.reached_when),
				sequence=m.sequence,
				disabled=m.disabled,
			).insert(ignore_permissions=True)
	for name in frappe.get_all("Opportunity", pluck="name"):
		refresh_bid_status(name)
