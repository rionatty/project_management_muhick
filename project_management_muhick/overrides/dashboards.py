# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.notifications import get_open_count


def get_project_dashboard(data):
	"""Every document of a project on its form's Connections tab, in the order the work goes. The bid, its quotation and
	the sales order are the project's own links, as they name no project; with none, the list opens empty rather than
	showing every bid. A request for quotation names the project on its lines as project_name. What ERPNext lists here
	and the work has no use for keeps its own heading, at the end."""
	groups = [
		{"label": _("Sales"), "items": ["Opportunity", "Quotation", "Sales Order", "Delivery Note", "Sales Invoice"]},
		{"label": _("Handover and Planning"), "items": ["Project Handover", "Project BOQ", "Project Activity Plan", "Task", "Project Update"]},
		{"label": _("Budget"), "items": ["Project Budget", "Project Budget Revision", "Project Requisition"]},
		{
			"label": _("Procurement"),
			"items": [
				"Material Request", "Request for Quotation", "Supplier Quotation", "Supplier Evaluation", "Procurement Report",
				"Procurement Requisition", "Purchase Order",
				"Purchase Receipt", "Purchase Invoice", "Import Shipment", "Specification Change Request",
			],
		},
		{"label": _("Stores and Equipment"), "items": ["Stock Entry", "Project Equipment Allocation", "Equipment Log", "Fuel Requisition"]},
		{"label": _("Payments"), "items": ["Payment Plan", "Payment Entry", "Journal Entry", "Reimbursement Claim", "Resource Allocation", "Bank Instrument"]},
		{"label": _("Labour and Subcontracts"), "items": ["Labour Schedule", "Casual Sheet", "Subcontract RFQ", "Subcontract Agreement", "Subcontract Advance", "Service Receipt Note"]},
		{"label": _("Claims and Completion"), "items": ["Project Claim", "Project Variation Order", "Retention Release", "Project Completion Certificate", "Project Defect", "Project Warranty"]},
		{"label": _("Site Records"), "items": ["Site Report", "Site Meeting", "Project Document"]},
	]
	placed = {item for group in groups for item in group["items"]}
	for group in data.get("transactions", []):
		rest = [item for item in group["items"] if item not in placed]
		if rest:
			groups.append({"label": group["label"], "items": rest})
	data["transactions"] = groups
	data.setdefault("internal_links", {}).update({"Opportunity": "muhick_bid", "Quotation": "muhick_quotation", "Sales Order": "sales_order"})
	data.setdefault("non_standard_fieldnames", {}).update(
		{"Request for Quotation": "project_name", "Opportunity": "name", "Quotation": "name", "Resource Allocation": "to_project"}
	)
	data["method"] = "project_management_muhick.overrides.dashboards.get_project_counts"
	return data


@frappe.whitelist()
def get_project_counts(doctype: str, name: str, items=None):
	"""The counts on a project's Connections tab. Money can be allocated from a project or to it, and no one field holds
	both, so its allocations are found by either and listed by name."""
	out = get_open_count(doctype, name, items)
	counts = out.get("count")
	if isinstance(counts, dict):
		names = frappe.get_all(
			"Resource Allocation", filters={"docstatus": ("<", 2)}, or_filters={"from_project": name, "to_project": name}, pluck="name"
		)
		counts["external_links_found"] = [row for row in counts["external_links_found"] if row["doctype"] != "Resource Allocation"]
		if names:
			counts["internal_links_found"].append({"doctype": "Resource Allocation", "open_count": 0, "count": len(names), "names": names})
	return out


def get_material_request_dashboard(data):
	"""A request's Procurement Report: where each of its items stands, and the supplier chosen."""
	data.setdefault("transactions", []).append({"label": _("Procurement"), "items": ["Procurement Report"]})
	return data


def get_request_for_quotation_dashboard(data):
	"""The evaluation that chose the suppliers of a request for quotation."""
	data.setdefault("transactions", []).append({"label": _("Selection"), "items": ["Supplier Evaluation"]})
	return data


def get_purchase_order_dashboard(data):
	"""What an import order leads to: its consignment and the letter of credit that pays for it."""
	data.setdefault("transactions", []).append({"label": _("Import"), "items": ["Import Shipment", "Bank Instrument"]})
	return data


def get_task_dashboard(data):
	"""On a milestone (a group task), the documents raised against it."""
	data.setdefault("non_standard_fieldnames", {}).update(
		{
			"Material Request": "muhick_phase", "Stock Entry": "muhick_phase", "Project Claim": "phase",
			"Labour Schedule": "phase", "Casual Sheet": "phase", "Project Requisition": "phase", "Subcontract RFQ": "phase",
		}
	)
	data.setdefault("transactions", []).extend(
		[
			{"label": _("Milestone Materials"), "items": ["Material Request", "Stock Entry"]},
			{"label": _("Milestone Labour and Claims"), "items": ["Labour Schedule", "Casual Sheet", "Project Requisition", "Subcontract RFQ", "Project Claim"]},
		]
	)
	return data


def get_opportunity_dashboard(data):
	"""On an opportunity (a bid), its sales requisitions, its bid security request, the security and its
	outcome report."""
	data.setdefault("transactions", []).append(
		{"label": _("Bid"), "items": ["Sales Requisition", "Bid Security Request", "Bank Instrument", "Bid Outcome"]}
	)
	return data
