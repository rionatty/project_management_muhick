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

# Client scripts
# --------------

# helpers shared by the Muhick forms
app_include_js = "/assets/project_management_muhick/js/muhick_common.js"

# scripts added to standard ERPNext forms

doctype_js = {
	"Project": "public/js/project.js",
	"Material Request": "public/js/material_request.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Supplier Quotation": "public/js/supplier_quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Stock Entry": "public/js/stock_entry.js",
}

override_doctype_dashboards = {
	"Project": "project_management_muhick.overrides.dashboards.get_project_dashboard",
}

# Document events
# ---------------

_track = "project_management_muhick.utils.approval.track"
_approval_events = {"on_update": _track, "on_submit": _track, "on_cancel": _track}

doc_events = {
	"Project": {
		"validate": "project_management_muhick.overrides.project.validate",
		"after_insert": "project_management_muhick.overrides.project.after_insert",
	},
	"Material Request": {
		"validate": "project_management_muhick.overrides.material_request.validate",
		**_approval_events,
	},
	"Supplier": {
		"validate": "project_management_muhick.overrides.supplier.validate",
		"after_insert": "project_management_muhick.overrides.supplier.after_insert",
	},
	"Supplier Quotation": _approval_events,
	"Purchase Order": {
		"validate": "project_management_muhick.overrides.buying.validate_purchase_order",
		"before_submit": "project_management_muhick.overrides.buying.before_submit_purchase_order",
		"on_update": _track,
		"on_submit": ["project_management_muhick.overrides.buying.on_submit_purchase_order", _track],
		"on_cancel": ["project_management_muhick.overrides.buying.on_cancel_purchase_order", _track],
		"on_update_after_submit": "project_management_muhick.overrides.buying.refresh_budgets",
	},
	"Purchase Receipt": {
		"validate": "project_management_muhick.overrides.buying.validate_purchase_receipt",
		**_approval_events,
	},
	"Payment Request": {
		"on_submit": "project_management_muhick.overrides.accounts.on_submit_payment_request",
	},
	"Journal Entry": {
		"on_submit": "project_management_muhick.overrides.accounts.on_submit_journal_entry",
		"on_cancel": "project_management_muhick.overrides.accounts.on_cancel_journal_entry",
	},
	"Purchase Invoice": {
		"validate": "project_management_muhick.overrides.buying.validate_purchase_invoice",
		"before_submit": "project_management_muhick.overrides.buying.before_submit_purchase_invoice",
		"on_submit": "project_management_muhick.overrides.buying.on_submit_purchase_invoice",
		"on_cancel": "project_management_muhick.overrides.buying.on_cancel_purchase_invoice",
	},
	"Payment Entry": {
		"validate": "project_management_muhick.overrides.accounts.validate_payment_entry",
		"on_submit": "project_management_muhick.overrides.accounts.after_payment",
		"on_cancel": "project_management_muhick.overrides.accounts.after_payment",
	},
	"Stock Entry": {
		"validate": "project_management_muhick.overrides.stock.validate_stock_entry",
		"on_update": _track,
		"on_submit": ["project_management_muhick.overrides.stock.refresh_budgets", _track],
		"on_cancel": ["project_management_muhick.overrides.stock.refresh_budgets", _track],
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
		"on_submit": "project_management_muhick.overrides.accounts.on_submit_sales_order",
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
	"Project Variation Order": _approval_events,
	"Project Handover": _approval_events,
	"Procurement Requisition": _approval_events,
	"Payment Plan": _approval_events,
	"Reimbursement Claim": _approval_events,
	"Project Fund Transfer": _approval_events,
	"Sales Requisition": _approval_events,
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
	],
}
