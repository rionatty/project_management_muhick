# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bids are standard Opportunities now. Each bid's details move onto its opportunity (one is made,
with a lead, for a bid that had none), its follow-ups become comments on the opportunity, its files
are attached there, and its sales requisitions and bid security point to it. A bid that cannot be
moved is logged, not raised, so the migration carries on. The old table is left in place."""

import frappe
from frappe.utils import getdate

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_crm_lists

STAGES = {
	"Identified": "Qualified", "Qualified": "Qualified", "In Preparation": "In Preparation",
	"Submitted": "Submitted", "Under Evaluation": "Under Evaluation", "Won": "Awarded",
}
# bid column -> opportunity field
FIELDS = {
	"tender_reference": "muhick_tender_reference", "advert": "muhick_advert",
	"submission_deadline": "muhick_submission_deadline", "site_visit_required": "muhick_site_visit_required",
	"site_visit_date": "muhick_site_visit_date", "financial_requirement": "muhick_financial_requirement",
	"qualification_notes": "muhick_qualification_notes", "estimated_cost": "muhick_estimated_cost",
	"margin_percent": "muhick_margin_percent", "administrative_bid_ready": "muhick_administrative_bid_ready",
	"technical_bid_ready": "muhick_technical_bid_ready", "financial_bid_ready": "muhick_financial_bid_ready",
	"submission_mode": "muhick_submission_mode", "submitted_on": "muhick_submitted_on",
	"bid_documents": "muhick_bid_documents", "bid_security_required": "muhick_bid_security_required",
	"bid_security": "muhick_bid_security", "bid_security_amount": "muhick_bid_security_amount",
	"award_notice": "muhick_award_notice", "outcome_date": "muhick_outcome_date",
}


def execute():
	if not frappe.db.table_exists("Bid"):
		return
	# the opportunity's bid fields and the lists are normally added after patches run
	setup_custom_fields()
	setup_crm_lists()
	for bid in frappe.db.sql("select * from `tabBid` order by creation", as_dict=True):
		frappe.db.savepoint("muhick_bid")
		try:
			move(bid)
		except Exception:
			frappe.db.rollback(save_point="muhick_bid")
			frappe.log_error(title=f"Muhick: moving bid {bid.name} to an opportunity failed")


def move(bid):
	opportunity = bid.opportunity if bid.opportunity and frappe.db.exists("Opportunity", bid.opportunity) else new_opportunity(bid)
	values = {
		field: bid.get(column)
		for column, field in FIELDS.items()
		if bid.get(column) not in (None, "") and frappe.db.has_column("Opportunity", field)
	}
	values["muhick_outcome_notes"] = "\n\n".join(filter(None, (bid.outcome_reason, bid.lessons))) or None
	if bid.bid_price and not frappe.db.get_value("Opportunity", opportunity, "opportunity_amount"):
		values["opportunity_amount"] = bid.bid_price
	if bid.status in STAGES:
		values["sales_stage"] = STAGES[bid.status]
	elif bid.status == "Lost":
		values.update(status="Lost", order_lost_reason=bid.outcome_reason)
	elif bid.status in ("Cancelled", "Not Pursued"):
		values["status"] = "Closed"
	frappe.db.set_value("Opportunity", opportunity, values, update_modified=False)
	for row in frappe.db.sql("select * from `tabBid Follow Up` where parent = %s order by idx", bid.name, as_dict=True):
		note = ": ".join(filter(None, (str(getdate(row.follow_up_date)), row.contact_person, row.notes)))
		frappe.get_doc(
			{
				"doctype": "CRM Note", "parent": opportunity, "parenttype": "Opportunity", "parentfield": "notes",
				"note": note, "added_by": row.followed_by, "added_on": row.follow_up_date,
			}
		).db_insert()
	frappe.db.sql(
		"update `tabFile` set attached_to_doctype = 'Opportunity', attached_to_name = %s "
		"where attached_to_doctype = 'Bid' and attached_to_name = %s",
		(opportunity, bid.name),
	)
	for doctype in ("Sales Requisition", "Bank Instrument"):
		if frappe.db.has_column(doctype, "bid"):
			frappe.db.sql(f"update `tab{doctype}` set opportunity = %s where bid = %s", (opportunity, bid.name))
	if frappe.db.has_column("Sales Requisition", "bid"):
		frappe.db.sql(
			"update `tabSales Requisition` set organisation = %s where opportunity = %s",
			(frappe.db.get_value("Opportunity", opportunity, "customer_name"), opportunity),
		)


def new_opportunity(bid):
	"""An opportunity for a bid that had none, from its client, its lead, or a new qualified lead."""
	if bid.customer:
		party_type, party = "Customer", bid.customer
	elif bid.lead and frappe.db.exists("Lead", bid.lead):
		party_type, party = "Lead", bid.lead
	else:
		lead = frappe.get_doc(
			{
				"doctype": "Lead", "company_name": bid.procuring_entity, "lead_owner": bid.assigned_to,
				"qualification_status": "Qualified", "muhick_requirement": bid.title, "company": bid.company,
				"utm_source": bid.lead_source if bid.lead_source and frappe.db.exists("UTM Source", bid.lead_source) else None,
			}
		)
		lead.insert(ignore_permissions=True, ignore_mandatory=True)
		party_type, party = "Lead", lead.name
	opportunity = frappe.get_doc(
		{
			"doctype": "Opportunity", "opportunity_from": party_type, "party_name": party, "company": bid.company,
			"opportunity_owner": bid.assigned_to, "muhick_requirement": bid.title, "transaction_date": getdate(bid.creation),
			"opportunity_type": bid.bid_type if bid.bid_type and frappe.db.exists("Opportunity Type", bid.bid_type) else None,
			"utm_source": bid.lead_source if bid.lead_source and frappe.db.exists("UTM Source", bid.lead_source) else None,
		}
	)
	opportunity.insert(ignore_permissions=True, ignore_mandatory=True)
	return opportunity.name
