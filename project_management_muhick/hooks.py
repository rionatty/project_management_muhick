app_name = "project_management_muhick"
app_title = "Project Management Muhick"
app_publisher = "CyveTech"
app_description = "Project budgeting and commitments, procurement approvals, site stores, claims, retention, payment plans and controls for ERPNext"
app_email = "info@cyvetech.com"
app_license = "Proprietary"

required_apps = ["frappe/erpnext"]

app_home = "/desk/muhick-projects"

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/project_management_muhick/images/muhick-logo.svg",
		"title": app_title,
		"route": "/desk/muhick-projects",
	}
]

# Installation
# ------------

after_install = "project_management_muhick.install.after_install"
after_migrate = "project_management_muhick.install.after_migrate"
before_uninstall = "project_management_muhick.install.before_uninstall"

# Client scripts
# --------------

# helpers shared by the Muhick forms, and one colour for the header buttons of every document; a bundle, so
# its file name changes with each version and browsers take the new one (a plain /assets file is cached
# for a year)
app_include_js = "muhick_common.bundle.js"
# every table in the desk: a bar to scroll sideways by when it has more columns than the page has room for
app_include_css = "muhick_common.bundle.css"

# scripts added to standard ERPNext forms

doctype_js = {
	"Project": ["public/js/activity_schedule.js", "public/js/project.js"],
	"Project Activity Plan": "public/js/activity_schedule.js",
	"Material Request": "public/js/material_request.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Supplier Quotation": "public/js/supplier_quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Task": "public/js/task.js",
	"Lead": "public/js/lead.js",
	"Opportunity": "public/js/opportunity.js",
	"Quotation": "public/js/quotation.js",
}

# the opportunity list shows each bid's status; several approved supplier quotations make one requisition
doctype_list_js = {
	"Opportunity": "public/js/opportunity_list.js",
	"Supplier Quotation": "public/js/supplier_quotation_list.js",
}

# for the Budget Summary print of a project budget and the Bid Budget print of an opportunity
jinja = {
	"methods": [
		"project_management_muhick.muhick_projects.estimate.budget_summary",
		"project_management_muhick.muhick_projects.estimate.bid_budget",
	]
}

override_doctype_dashboards = {
	"Project": "project_management_muhick.overrides.dashboards.get_project_dashboard",
	"Task": "project_management_muhick.overrides.dashboards.get_task_dashboard",
	"Opportunity": "project_management_muhick.overrides.dashboards.get_opportunity_dashboard",
	"Purchase Order": "project_management_muhick.overrides.dashboards.get_purchase_order_dashboard",
}

# Document events
# ---------------

_track = "project_management_muhick.utils.approval.track"
_approval_events = {"on_update": _track, "on_submit": _track, "on_cancel": _track}
# keeps the requested / purchased / consumed quantities on the project's BOQ lines current
_boq = "project_management_muhick.muhick_projects.doctype.project_boq.project_boq.refresh_from_document"

doc_events = {
	"Lead": {"validate": "project_management_muhick.overrides.crm.validate_lead"},
	"Opportunity": {
		"validate": "project_management_muhick.overrides.crm.validate_opportunity",
		"on_update": "project_management_muhick.overrides.crm.on_update_opportunity",
	},
	"Quotation": {
		"on_submit": "project_management_muhick.overrides.crm.refresh_from_sale",
		"on_cancel": "project_management_muhick.overrides.crm.quotation_cancelled",
	},
	"Project": {
		"validate": "project_management_muhick.overrides.project.validate",
		"after_insert": "project_management_muhick.overrides.project.after_insert",
	},
	"Material Request": {
		"validate": "project_management_muhick.overrides.material_request.validate",
		"on_update": _track,
		"on_submit": [_track, _boq],
		"on_cancel": [_track, _boq],
	},
	"Task": {
		"validate": "project_management_muhick.overrides.task.validate",
		"on_update": "project_management_muhick.overrides.task.on_update",
	},
	"Supplier": {
		"validate": "project_management_muhick.overrides.supplier.validate",
		"after_insert": "project_management_muhick.overrides.supplier.after_insert",
	},
	"Request for Quotation": {"validate": "project_management_muhick.overrides.buying.validate_request_for_quotation"},
	"Supplier Quotation": {**_approval_events, "validate": "project_management_muhick.overrides.buying.validate_supplier_quotation"},
	"Purchase Order": {
		"validate": "project_management_muhick.overrides.buying.validate_purchase_order",
		"before_submit": "project_management_muhick.overrides.buying.before_submit_purchase_order",
		"on_update": _track,
		"on_submit": ["project_management_muhick.overrides.buying.on_submit_purchase_order", _track, _boq],
		"on_cancel": ["project_management_muhick.overrides.buying.on_cancel_purchase_order", _track, _boq],
		"on_update_after_submit": ["project_management_muhick.overrides.buying.refresh_budgets", _boq],
	},
	"Purchase Receipt": {
		"validate": "project_management_muhick.overrides.buying.validate_purchase_receipt",
		**_approval_events,
		"on_submit": [_track, "project_management_muhick.muhick_controls.matching.recheck_on_receipt"],
		"on_cancel": [_track, "project_management_muhick.muhick_controls.matching.recheck_on_receipt"],
	},
	"Payment Request": {
		**_approval_events,
		"validate": "project_management_muhick.overrides.accounts.validate_payment_request",
		"on_submit": [_track, "project_management_muhick.overrides.accounts.on_submit_payment_request"],
	},
	"Bank Account": {
		"on_update": "project_management_muhick.overrides.accounts.bank_details_changed",
	},
	"Journal Entry": {
		"on_submit": "project_management_muhick.overrides.accounts.on_submit_journal_entry",
		"on_cancel": "project_management_muhick.overrides.accounts.on_cancel_journal_entry",
		"on_trash": "project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan.payment_deleted",
	},
	"Purchase Invoice": {
		"before_validate": "project_management_muhick.overrides.buying.before_validate_purchase_invoice",
		"validate": "project_management_muhick.overrides.buying.validate_purchase_invoice",
		"before_submit": "project_management_muhick.overrides.buying.before_submit_purchase_invoice",
		"on_submit": "project_management_muhick.overrides.buying.on_submit_purchase_invoice",
		"on_cancel": "project_management_muhick.overrides.buying.on_cancel_purchase_invoice",
	},
	"Payment Entry": {
		"validate": "project_management_muhick.overrides.accounts.validate_payment_entry",
		"on_submit": "project_management_muhick.overrides.accounts.after_payment",
		"on_cancel": "project_management_muhick.overrides.accounts.after_payment",
		"on_trash": [
			"project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan.payment_deleted",
			"project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.transfer_deleted",
		],
	},
	"Stock Entry": {
		"before_validate": "project_management_muhick.overrides.stock.before_validate_stock_entry",
		"validate": "project_management_muhick.overrides.stock.validate_stock_entry",
		"on_update": _track,
		"on_submit": ["project_management_muhick.overrides.stock.refresh_budgets", _track, _boq],
		"on_cancel": ["project_management_muhick.overrides.stock.refresh_budgets", _track, _boq],
	},
	"Delivery Note": {
		"validate": "project_management_muhick.overrides.stock.validate_delivery_note",
		**_approval_events,
	},
	"Warehouse": {
		"validate": "project_management_muhick.overrides.stock.validate_warehouse",
	},
	"Sales Invoice": {
		"on_submit": "project_management_muhick.overrides.accounts.on_submit_sales_invoice",
		"on_cancel": "project_management_muhick.overrides.accounts.on_cancel_sales_invoice",
	},
	"Sales Order": {
		"on_submit": [
			"project_management_muhick.overrides.accounts.on_submit_sales_order",
			"project_management_muhick.overrides.crm.refresh_from_sale",
		],
		"on_update_after_submit": "project_management_muhick.overrides.accounts.sale_type_changed",
		"on_cancel": "project_management_muhick.overrides.crm.refresh_from_sale",
	},
	# documents of this app that move through an approval workflow
	"Project Budget": _approval_events,
	"Project Budget Revision": _approval_events,
	"Project Activity Plan": _approval_events,
	"Project Requisition": _approval_events,
	"Labour Schedule": _approval_events,
	"Casual Sheet": _approval_events,
	"Subcontract RFQ": _approval_events,
	"Subcontract Agreement": _approval_events,
	"Subcontract Advance": _approval_events,
	"Project Variation Order": _approval_events,
	"Project Handover": _approval_events,
	"Procurement Requisition": _approval_events,
	"Payment Plan": _approval_events,
	"Reimbursement Claim": _approval_events,
	"Resource Allocation": _approval_events,
	"Sales Requisition": _approval_events,
	"Bid Security Request": _approval_events,
	"Bid Outcome": _approval_events,
	"Fuel Requisition": _approval_events,
	"Vehicle Service Request": _approval_events,
}

# Scheduled tasks
# ---------------

scheduler_events = {
	"hourly": [
		"project_management_muhick.utils.approval.send_overdue_alerts",
	],
	"daily": [
		"project_management_muhick.overrides.project.send_dlp_reminders",
		"project_management_muhick.muhick_projects.budget_engine.refresh_all_budgets",
		"project_management_muhick.utils.reminders.send_daily_reminders",
		"project_management_muhick.overrides.crm.refresh_bid_statuses",
	],
}
