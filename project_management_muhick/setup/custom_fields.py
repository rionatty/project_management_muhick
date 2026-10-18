# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Fields the app adds to standard ERPNext documents. All are prefixed muhick_."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

BUDGET_STATUS = "\nWithin Budget\nExceeds Budget\nNot Budgeted\nNot Applicable"
COST_CODE = dict(fieldname="muhick_cost_code", label="Cost Code", fieldtype="Link", options="Cost Code", insert_after="project")


def _chain(after, fields):
	"""Place each field after the previous one, starting after an existing field."""
	out = []
	for f in fields:
		f = dict(f, insert_after=after)
		out.append(f)
		after = f["fieldname"]
	return out


def _sec(name, label=None, **kw):
	field = dict(fieldname=name, fieldtype="Section Break", **kw)
	if label:
		field["label"] = label
	return field


def _col(name):
	return dict(fieldname=name, fieldtype="Column Break")


def _ro(fieldname, label, fieldtype="Currency", **kw):
	return dict(fieldname=fieldname, label=label, fieldtype=fieldtype, read_only=1, no_copy=1, **kw)


PROJECT = _chain(
	"notes",
	[
		dict(fieldname="muhick_contract_tab", fieldtype="Tab Break", label="Contract and Lifecycle"),
		_sec("muhick_lifecycle_section", "Lifecycle"),
		dict(fieldname="muhick_stage", label="Stage", fieldtype="Select", options="Planning\nExecution\nPractical Completion\nFull Completion", default="Planning", read_only=1, no_copy=1, in_standard_filter=1, in_list_view=1, description="Practical Completion means the project is in its Defects Liability Period"),
		dict(fieldname="muhick_project_category", label="Project Category", fieldtype="Select", options="\nSupply and Install\nSupply Only\nWorks\nConsultancy\nOther"),
		dict(fieldname="muhick_project_manager", label="Project Manager", fieldtype="Link", options="User", in_standard_filter=1),
		dict(fieldname="muhick_sales_engineer", label="Sales Engineer (Result Support)", fieldtype="Link", options="User"),
		_col("muhick_lifecycle_column"),
		_ro("muhick_handover", "Sales Handover", "Link", options="Project Handover"),
		_ro("muhick_boq", "Bill of Quantities", "Link", options="Project BOQ"),
		_ro("muhick_budget", "Approved Budget", "Link", options="Project Budget"),
		_ro("muhick_activity_plan", "Approved Activity Plan", "Link", options="Project Activity Plan"),
		_sec("muhick_contract_section", "Contract"),
		dict(fieldname="muhick_contract_no", label="Contract No.", fieldtype="Data"),
		dict(fieldname="muhick_contract_date", label="Contract Date", fieldtype="Date"),
		dict(fieldname="muhick_contract_value", label="Original Contract Value", fieldtype="Currency"),
		_ro("muhick_approved_variations", "Approved Variations"),
		_ro("muhick_revised_contract_value", "Revised Contract Value", bold=1),
		_col("muhick_contract_column"),
		dict(fieldname="muhick_contract_start", label="Contract Start", fieldtype="Date"),
		dict(fieldname="muhick_contract_end", label="Contract End", fieldtype="Date"),
		dict(fieldname="muhick_client_representative", label="Client Representative", fieldtype="Data"),
		dict(fieldname="muhick_site_location", label="Site Location", fieldtype="Data"),
		_sec("muhick_billing_section", "Billing Terms"),
		dict(fieldname="muhick_billing_method", label="Billing Method", fieldtype="Select", options="\nMilestone\nMonthly Valuation\nOne-off at Completion"),
		dict(fieldname="muhick_advance_percent", label="Advance Payment %", fieldtype="Percent"),
		dict(fieldname="muhick_advance_amount", label="Advance Payment Amount", fieldtype="Currency"),
		_col("muhick_billing_column"),
		dict(fieldname="muhick_retention_percent", label="Retention %", fieldtype="Percent", description="Leave at zero for contracts with no retention"),
		dict(fieldname="muhick_dlp_months", label="Defects Liability Period (Months)", fieldtype="Int"),
		_sec("muhick_site_store_section", "Site Store"),
		_ro("muhick_site_warehouse", "Site Store", "Link", options="Warehouse"),
		_col("muhick_site_store_column"),
		dict(fieldname="muhick_site_store_type", label="Store Run By", fieldtype="Select", options="Company\nClient", default="Company", description="Client: a store belonging to the client or shared with other contractors. Stock stays the company's until it is installed."),
		_sec("muhick_completion_section", "Completion"),
		_ro("muhick_practical_completion_date", "Practical Completion Date", "Date"),
		_ro("muhick_dlp_end_date", "Defects Liability Ends On", "Date"),
		_col("muhick_completion_column"),
		_ro("muhick_final_completion_date", "Full Completion Date", "Date"),
		_ro("muhick_last_dlp_reminder", "Last DLP Reminder", "Date", hidden=1),
		_sec("muhick_position_section", "Certified Position"),
		_ro("muhick_certified_to_date", "Certified to Date"),
		_ro("muhick_retention_held", "Retention Held by Client"),
		_col("muhick_position_column"),
		_ro("muhick_retention_released", "Retention Released"),
		_ro("muhick_advance_recovered", "Advance Recovered"),
		_sec("muhick_opening_section", "Position Before Go-Live", collapsible=1),
		dict(fieldname="muhick_opening_certified", label="Certified Before Go-Live", fieldtype="Currency", description="Only for projects already running when the system went live"),
		dict(fieldname="muhick_opening_retention_held", label="Retention Held Before Go-Live", fieldtype="Currency"),
		_col("muhick_opening_column"),
		dict(fieldname="muhick_opening_retention_released", label="Retention Released Before Go-Live", fieldtype="Currency"),
		dict(fieldname="muhick_opening_advance_recovered", label="Advance Recovered Before Go-Live", fieldtype="Currency"),
		_sec("muhick_brands_section", "Client-Approved Brands and Specifications"),
		dict(fieldname="muhick_approved_brands", label="Approved Brands", fieldtype="Table", options="Project Approved Brand"),
	],
)

MATERIAL_REQUEST = _chain(
	"amended_from",
	[
		_sec("muhick_project_section", "Project and Budget"),
		dict(fieldname="muhick_request_origin", label="Request From", fieldtype="Select", options="\nProject\nDefects Liability\nSite Store\nUser Department\nAdministration\nFixed Asset", in_standard_filter=1),
		dict(fieldname="muhick_project", label="Project", fieldtype="Link", options="Project", in_standard_filter=1),
		dict(fieldname="muhick_phase", label="Milestone / Phase", fieldtype="Link", options="Task", mandatory_depends_on="eval:doc.muhick_project && doc.muhick_request_origin=='Project'", description="Project requests are raised per milestone. Get Items from Milestone loads what the activity plan still needs for it."),
		_col("muhick_project_column"),
		dict(fieldname="muhick_budget_status", label="Budget Status", fieldtype="Select", options=BUDGET_STATUS, read_only=1, no_copy=1, in_standard_filter=1, allow_on_submit=1),
		dict(fieldname="muhick_budget_remarks", label="Budget Check", fieldtype="Small Text", read_only=1, no_copy=1, allow_on_submit=1),
		dict(fieldname="muhick_out_of_phase", label="Outside the Current Phase", fieldtype="Check", read_only=1, no_copy=1),
		dict(fieldname="muhick_justification", label="Justification", fieldtype="Small Text", description="Required when the request exceeds the budget or belongs to a later phase"),
		_col("muhick_urgency_column"),
		dict(fieldname="muhick_priority", label="Priority", fieldtype="Select", options="Normal\nHigh\nUrgent", default="Normal", in_standard_filter=1),
		dict(fieldname="muhick_priority_reason", label="Reason for the Priority", fieldtype="Small Text", depends_on="eval:doc.muhick_priority!='Normal'", mandatory_depends_on="eval:doc.muhick_priority=='Urgent'"),
		dict(fieldname="muhick_stock_status", label="Stock Check", fieldtype="Select", options="\nIn Stock\nInsufficient Stock\nNot Applicable", read_only=1, no_copy=1, description="For requests drawn from the stores: whether the source store holds enough"),
		dict(fieldname="muhick_spec_exception", label="Brand / Specification Check", fieldtype="Small Text", read_only=1, no_copy=1),
		dict(fieldname="muhick_stock_note", label="Already Held in Stock", fieldtype="Small Text", read_only=1, no_copy=1),
	],
)

PURCHASE_INVOICE = _chain(
	"hold_comment",
	[
		_sec("muhick_match_section", "Three-Way Match"),
		dict(fieldname="muhick_match_status", label="Match Status", fieldtype="Select", options="\nNot Applicable\nMatched\nException\nOverridden", read_only=1, no_copy=1, in_standard_filter=1, allow_on_submit=1),
		_ro("muhick_match_overridden_by", "Override By", "Link", options="User", allow_on_submit=1),
		_col("muhick_match_column"),
		dict(fieldname="muhick_match_remarks", label="Match Exceptions", fieldtype="Small Text", read_only=1, no_copy=1, allow_on_submit=1),
	],
) + _chain(
	"project",
	[
		dict(fieldname="muhick_subcontract_agreement", label="Subcontract Agreement", fieldtype="Link", options="Subcontract Agreement", no_copy=1),
		dict(fieldname="muhick_service_receipt_note", label="Service Receipt Note", fieldtype="Link", options="Service Receipt Note", no_copy=1),
	],
)

CUSTOM_FIELDS = {
	"Project": PROJECT,
	"Material Request": MATERIAL_REQUEST,
	"Material Request Item": [dict(COST_CODE)],
	"Purchase Order Item": [dict(COST_CODE)],
	"Purchase Receipt Item": [dict(COST_CODE)],
	"Purchase Invoice Item": [dict(COST_CODE)],
	"Purchase Invoice": PURCHASE_INVOICE,
	"Stock Entry": _chain(
		"project",
		[
			dict(fieldname="muhick_phase", label="Milestone / Phase", fieldtype="Link", options="Task"),
			_ro("muhick_purchase_order", "Delivery of Purchase Order", "Link", options="Purchase Order"),
			dict(fieldname="muhick_is_disposal", label="Disposal / Write-Off", fieldtype="Check", depends_on="eval:doc.purpose=='Material Issue'", description="Damaged, expired or obsolete stock being disposed of. Needs Finance approval."),
			dict(fieldname="muhick_disposal_reason", label="Reason for Disposal", fieldtype="Small Text", depends_on="eval:doc.muhick_is_disposal", mandatory_depends_on="eval:doc.muhick_is_disposal"),
			dict(fieldname="muhick_approval_route", label="Approval Needed From", fieldtype="Select", options="\nProcurement Manager\nFinance", read_only=1, no_copy=1),
		],
	),
	"Stock Entry Detail": _chain(
		"project",
		[
			dict(COST_CODE),
			dict(fieldname="muhick_charge_to_project", label="Charge to Project Budget", fieldtype="Check", description="Ticked when the stock comes from the company's own stores. Untick if it was bought on a purchase order for this project, which is already a commitment."),
		],
	),
	"Sales Invoice": _chain(
		"project",
		[
			_ro("muhick_project_claim", "Project Claim", "Link", options="Project Claim"),
			_ro("muhick_retention_release", "Retention Release", "Link", options="Retention Release"),
		],
	),
	"Sales Order": [
		dict(fieldname="muhick_sale_type", label="Sale Type", fieldtype="Select", options="\nStock\nProject\nAdditions", insert_after="order_type", description="Project and Additions notify the Project Manager and start the handover"),
	],
	# a milestone (phase) is a group task, its activities are child tasks; these hold what the approved plan sets
	"Task": _chain(
		"is_milestone",
		[
			_sec("muhick_overview_section", "Milestone Overview", depends_on="eval:doc.is_group && !doc.__islocal"),
			dict(fieldname="muhick_milestone_overview", label="Milestone Overview", fieldtype="HTML"),
			_sec("muhick_plan_section", "Milestone Plan and Billing", collapsible=1),
			_ro("muhick_activity_plan", "Activity Plan", "Link", options="Project Activity Plan"),
			_ro("muhick_baseline_start", "Baseline Start", "Date"),
			_ro("muhick_baseline_end", "Baseline End", "Date"),
			_col("muhick_plan_column"),
			_ro("muhick_is_billing_milestone", "Billing Milestone", "Check", depends_on="eval:doc.is_group"),
			_ro("muhick_planned_valuation", "Planned Valuation", depends_on="eval:doc.is_group"),
			_ro("muhick_planned_claim_date", "Planned Claim Date", "Date", depends_on="eval:doc.is_group"),
			_ro("muhick_billing_status", "Billing Status", "Select", options="\nClaimed\nCertified", depends_on="eval:doc.is_group"),
		],
	),
	"Item": [
		dict(fieldname="muhick_cost_code", label="Default Cost Code", fieldtype="Link", options="Cost Code", insert_after="item_group", description="Proposed on budget lines and requests for this item"),
	],
	"Warehouse": _chain(
		"warehouse_type",
		[
			dict(fieldname="muhick_store_type", label="Store Type", fieldtype="Select", options="\nCentral Store\nSite Store\nClient Store\nGoods In Transit\nQuarantine", in_standard_filter=1),
			dict(fieldname="muhick_project", label="Project", fieldtype="Link", options="Project", depends_on="eval:in_list(['Site Store','Client Store'], doc.muhick_store_type)"),
			dict(fieldname="muhick_stock_ownership", label="Stock Owned By", fieldtype="Select", options="\nCompany\nProject\nClient"),
		],
	),
	"Supplier": [
		dict(fieldname="muhick_is_subcontractor", label="Is Subcontractor", fieldtype="Check", insert_after="is_transporter"),
		*_chain(
			"customer_numbers",
			[
				dict(fieldname="muhick_onboarding_tab", fieldtype="Tab Break", label="Onboarding"),
				dict(fieldname="muhick_onboarding_status", label="Onboarding Status", fieldtype="Select", options="\nNot Required\nPending\nApproved\nRejected", in_standard_filter=1, no_copy=1),
				_ro("muhick_onboarding_approved_by", "Approved By", "Link", options="User"),
				dict(fieldname="muhick_onboarding_checklist", label="Onboarding Requirements", fieldtype="Table", options="Supplier Onboarding Item"),
			],
		),
	],
	"Purchase Order": _chain(
		"project",
		[
			_ro("muhick_procurement_requisition", "Procurement Requisition", "Link", options="Procurement Requisition"),
			dict(fieldname="muhick_payment_type", label="Payment Terms Type", fieldtype="Select", options="\nAdvance\nOn Delivery\nCredit"),
			dict(fieldname="muhick_advance_percent", label="Advance %", fieldtype="Percent", depends_on="eval:doc.muhick_payment_type=='Advance'"),
			dict(fieldname="muhick_delivery_location", label="Delivery Location", fieldtype="Data"),
			dict(fieldname="muhick_acceptance_criteria", label="Acceptance Criteria", fieldtype="Small Text"),
		],
	),
	"Payment Entry": _chain(
		"project",
		[
			dict(fieldname="muhick_payment_plan", label="Payment Plan", fieldtype="Link", options="Payment Plan", no_copy=1),
			dict(fieldname="muhick_payment_plan_line", label="Payment Plan Line", fieldtype="Data", hidden=1, no_copy=1),
		],
	),
	"Journal Entry": [
		_ro("muhick_reimbursement_claim", "Reimbursement Claim", "Link", options="Reimbursement Claim", insert_after="user_remark"),
	],
}


# standard fields shown the way this app uses them: (doctype, field or None for the doctype, property, value, type)
PROPERTY_SETTERS = (
	("Task", "parent_task", "label", "Milestone / Phase", "Data"),
	("Task", "parent_task", "description", "The milestone (a group task of the project) this task belongs to", "Text"),
	("Task", "parent_task", "in_list_view", "1", "Check"),
	("Task", "parent_task", "in_standard_filter", "1", "Check"),
	# links to a task show its name (subject), not TASK-2026-00012
	("Task", None, "show_title_field_in_link", "1", "Check"),
)


def setup_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	for doctype, fieldname, prop, value, prop_type in PROPERTY_SETTERS:
		filters = {"doc_type": doctype, "property": prop, "field_name": fieldname or ("is", "not set")}
		if frappe.db.get_value("Property Setter", filters, "value") != value:
			make_property_setter(doctype, fieldname, prop, value, prop_type, for_doctype=not fieldname, validate_fields_for_doctype=False)
