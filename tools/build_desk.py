"""Build-time helper (run from the repo root): writes the workspace, sidebar, desktop icons, number cards and charts."""

import datetime
import glob
import json
import os
import random
import string
import sys

os.chdir(sys.argv[1])
random.seed(7)
# a fresh timestamp: migrate re-imports a desk file only when it is newer than the site's copy
TS = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
WS = "Muhick Projects"
BASE = {"creation": TS, "modified": TS, "modified_by": "Administrator", "owner": "Administrator", "docstatus": 0, "idx": 0}


def rid():
	return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(10))


def dump(path, d):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8", newline="\n") as fh:
		fh.write(json.dumps(d, indent=1, sort_keys=True, separators=(",", ": ")) + "\n")


def scrub(name):
	return name.lower().replace(" ", "_").replace("-", "_")


D, R = "D", "R"
# (card, [(label, link_to, kind)])  kind: D = DocType, R = Report
CARDS = [
	("Handover and Planning", [
		("Project", "Project", D), ("Project Handover", "Project Handover", D), ("Bill of Quantities", "Project BOQ", D),
		("Activity Plan", "Project Activity Plan", D),
		# filtered views of the standard Task list: a milestone is a group task, its activities child tasks
		("Milestones (Master List)", "Task Type", D),
		("Project Milestones", "Task", D, [["Task", "is_group", "=", 1]]),
		("Tasks", "Task", D, [["Task", "is_group", "=", 0]]),
	]),
	("Budget and Cost Control", [
		("Project Budget", "Project Budget", D), ("Budget Revision / Cost Control Sheet", "Project Budget Revision", D),
		("Material Request", "Material Request", D), ("Cash Requisition", "Project Requisition", D),
	]),
	("Procurement", [
		("Supplier Quotation", "Supplier Quotation", D), ("Procurement Requisition", "Procurement Requisition", D),
		("Purchase Order", "Purchase Order", D), ("Goods Received Note", "Purchase Receipt", D),
		("Consignment Tracking", "Import Shipment", D), ("Specification Change Request", "Specification Change Request", D),
	]),
	("Payments and Claims", [
		("Payment Plan", "Payment Plan", D), ("Expense Claim", "Reimbursement Claim", D),
		("Payment Request", "Payment Request", D), ("Payment Entry", "Payment Entry", D),
	]),
	("Bank and Funds", [
		("Bank Facility", "Bank Facility", D), ("Bank Instrument", "Bank Instrument", D),
		("Funds Between Projects", "Project Fund Transfer", D),
	]),
	("Labour and Subcontracts", [
		("Labour Schedule", "Labour Schedule", D), ("Casual Sheet", "Casual Sheet", D), ("Subcontract RFQ", "Subcontract RFQ", D),
		("Subcontract Agreement", "Subcontract Agreement", D), ("Service Receipt Note", "Service Receipt Note", D),
	]),
	("Claims and Completion", [
		("Claim / Service Delivery Note", "Project Claim", D), ("Variation Order", "Project Variation Order", D),
		("Retention Release", "Retention Release", D), ("Completion Certificate", "Project Completion Certificate", D),
		("Defect", "Project Defect", D),
	]),
	("Site Records", [
		("Site Report", "Site Report", D), ("Site Meeting", "Site Meeting", D), ("Project Document", "Project Document", D),
		("Equipment Allocation", "Project Equipment Allocation", D), ("Equipment Log", "Equipment Log", D),
		("Warranty", "Project Warranty", D),
	]),
	("Sales and Bids", [
		("Lead", "Lead", D), ("Opportunity (Bid)", "Opportunity", D), ("Bid Documents", "Bid Document", D),
		("Sales Requisition", "Sales Requisition", D),
		("Bid Security Request", "Bid Security Request", D), ("Bid Outcome", "Bid Outcome", D),
		("Bid Register", "Bid Register", R), ("Bid Margin Comparison", "Bid Margin Comparison", R),
		("Financial Requirement Types", "Financial Requirement Type", D),
		("Bid Document Types", "Bid Document Type", D),
	]),
	("Administration", [
		("Fuel Requisition", "Fuel Requisition", D), ("Vehicle Service Request", "Vehicle Service Request", D),
		("Vehicle", "Vehicle", D), ("Stationery Issue", "Stationery Issue", D), ("Service Contract", "Service Contract", D),
		("Facility Maintenance", "Facility Maintenance Schedule", D),
		("Fuel Consumption", "Fuel Consumption", R), ("Vehicle Maintenance", "Vehicle Maintenance", R),
	]),
	("Project Reports", [
		("Project Portfolio", "Project Portfolio", R), ("Project Cost Report", "Project Cost Report", R),
		("Project Material Consumption", "Project Material Consumption", R), ("Phase Plan", "Phase Plan", R),
		("Proposed vs Certified Valuations", "Proposed vs Certified Valuations", R), ("Procurement Plan", "Procurement Plan", R),
		("Retention Register", "Retention Register", R), ("Subcontractor Performance", "Subcontractor Performance", R),
		("Equipment History", "Equipment History", R),
	]),
	("Procurement and Finance Reports", [
		("Project Procurement Status", "Project Procurement Status", R), ("Item Price Trend", "Item Price Trend", R),
		("Freight Forwarder Performance", "Freight Forwarder Performance", R),
		("Resource Envelope", "Resource Envelope", R), ("Bank Facility Utilisation", "Bank Facility Utilisation", R),
		("Payment Plan Execution", "Payment Plan Execution", R), ("Withholding Tax Register", "Withholding Tax Register", R),
	]),
	("Controls", [
		("Pending Approvals", "Pending Approvals", R), ("Three Way Match Exceptions", "Three Way Match Exceptions", R),
		("Role Permission Matrix", "Role Permission Matrix", R), ("Approval Turnaround Log", "Approval Turnaround Log", D),
	]),
	# what ERPNext's own Projects workspace offers, so one icon covers everything
	("Timesheets and Standard Project Tools", [
		("Timesheet", "Timesheet", D), ("Activity Type", "Activity Type", D), ("Activity Cost", "Activity Cost", D),
		("Project Type", "Project Type", D), ("Project Update", "Project Update", D), ("Projects Settings", "Projects Settings", D),
		("Project Summary", "Project Summary", R), ("Daily Timesheet Summary", "Daily Timesheet Summary", R),
		("Timesheet Billing Summary", "Timesheet Billing Summary", R),
		("Project wise Stock Tracking", "Project wise Stock Tracking", R), ("Delayed Tasks Summary", "Delayed Tasks Summary", R),
	]),
	("Setup", [
		("Muhick Settings", "Muhick Settings", D), ("Phase Templates", "Project Template", D), ("Cost Code", "Cost Code", D),
		("Labour Trade", "Labour Trade", D),
	]),
]
SHORTCUTS = [
	("Project", "Project", "DocType"), ("Project Budget", "Project Budget", "DocType"), ("Material Request", "Material Request", "DocType"),
	("Claim", "Project Claim", "DocType"), ("Pending Approvals", "Pending Approvals", "Report"), ("Project Portfolio", "Project Portfolio", "Report"),
]
ICONS = {
	"Handover and Planning": "milestone", "Budget and Cost Control": "accounting", "Procurement": "buying",
	"Payments and Claims": "accounting", "Bank and Funds": "money-coins-1", "Labour and Subcontracts": "users",
	"Claims and Completion": "money-coins-1", "Site Records": "file", "Sales and Bids": "sell", "Administration": "organization",
	"Project Reports": "chart", "Procurement and Finance Reports": "chart", "Controls": "lock", "Timesheets and Standard Project Tools": "list", "Setup": "database",
}
CLOSED_SECTIONS = ("Controls", "Setup", "Administration", "Procurement and Finance Reports", "Timesheets and Standard Project Tools")

# ------------------------------------------------------------------ number cards and charts
# (name, module dir, module, doctype, filters)
NUMBER_CARDS = [
	("Approvals Pending", "muhick_projects", "Muhick Projects", "Approval Turnaround Log", [["Approval Turnaround Log", "is_open", "=", 1]]),
	("Claims With the Client", "muhick_projects", "Muhick Projects", "Project Claim", [["Project Claim", "status", "=", "Submitted to Client"]]),
	("Certificates to Invoice", "muhick_projects", "Muhick Projects", "Project Claim", [["Project Claim", "status", "=", "Certified"]]),
	("Open Defects", "muhick_projects", "Muhick Projects", "Project Defect", [["Project Defect", "status", "in", ["Open", "In Progress"]]]),
	("Requisitions to Account For", "muhick_projects", "Muhick Projects", "Project Requisition", [["Project Requisition", "status", "in", ["Paid", "Accountability Submitted"]]]),
	("Bids in Progress", "muhick_sales", "Muhick Sales", "Opportunity", [["Opportunity", "sales_stage", "in", [
		"Qualified", "In Preparation", "Submitted", "Under Evaluation", "Outcome Pending Approval",
	]]]),
]
for name, mdir, module, doctype, filters in NUMBER_CARDS:
	dump(f"project_management_muhick/{mdir}/number_card/{scrub(name)}/{scrub(name)}.json", {
		**BASE, "aggregate_function_based_on": "", "currency": "", "doctype": "Number Card", "document_type": doctype,
		"dynamic_filters_json": "[]", "filters_json": json.dumps(filters, separators=(",", ":")), "function": "Count",
		"is_public": 1, "is_standard": 1, "label": name, "module": module, "name": name, "parent_document_type": "",
		"report_function": "Sum", "show_full_number": 0, "show_percentage_stats": 1, "stats_time_interval": "Daily",
		"type": "Document Type",
	})

CHART_COMMON = {
	**BASE, "currency": "", "doctype": "Dashboard Chart", "dynamic_filters_json": "[]", "is_public": 1, "is_standard": 1,
	"number_of_groups": 0, "parent_document_type": "", "roles": [], "show_values_over_chart": 0, "source": "",
	"use_report_chart": 0, "y_axis": [],
}
CHARTS = [
	("Certified Work by Month", "muhick_projects", {
		"module": "Muhick Projects", "document_type": "Project Claim", "chart_type": "Sum", "value_based_on": "certified_amount",
		"based_on": "certificate_date", "timeseries": 1, "time_interval": "Monthly", "timespan": "Last Year", "type": "Bar",
		"group_by_type": "Count",
		"filters_json": json.dumps([["Project Claim", "status", "in", ["Certified", "Invoiced", "Paid"]]], separators=(",", ":")),
	}),
	("Bids by Status", "muhick_sales", {
		"module": "Muhick Sales", "document_type": "Opportunity", "chart_type": "Group By", "group_by_based_on": "sales_stage",
		"group_by_type": "Count", "timeseries": 0, "type": "Donut", "filters_json": "[]", "value_based_on": "",
	}),
]
for name, mdir, extra in CHARTS:
	dump(f"project_management_muhick/{mdir}/dashboard_chart/{scrub(name)}/{scrub(name)}.json", {**CHART_COMMON, **extra, "chart_name": name, "name": name})

# ------------------------------------------------------------------ workspace
links = []
for card, entries in CARDS:
	# workspace links cannot carry filters: filtered entries become one plain link
	plain = [e[:3] for e in entries if len(e) == 3]
	if any(len(e) == 4 for e in entries):
		plain.append(("Milestones and Tasks", next(e[1] for e in entries if len(e) == 4), D))
	links.append({"hidden": 0, "is_query_report": 0, "label": card, "link_count": len(plain), "onboard": 0, "type": "Card Break"})
	for label, to, kind in plain:
		links.append({
			"dependencies": "", "hidden": 0, "is_query_report": 1 if kind == R else 0, "label": label, "link_count": 0,
			"link_to": to, "link_type": "Report" if kind == R else "DocType", "onboard": 0, "type": "Link",
		})
shortcuts = []
for label, to, typ in SHORTCUTS:
	s = {"color": "Grey", "label": label, "link_to": to, "type": typ}
	if typ == "DocType":
		s["doc_view"] = "List"
	shortcuts.append(s)

# ERPNext's own project dashboards (records shipped by ERPNext), first on the page: one icon covers both
STANDARD_CHARTS = [("Completed Projects", "Completed Projects"), ("Project Summary", "Project Summary")]
STANDARD_NUMBER_CARDS = [("Open Projects", "Open Projects"), ("Non Completed Tasks", "Non Completed Tasks"), ("Timesheet Working Hours", "Working Hours")]

content = [{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Projects at a Glance</b></span>', "col": 12}}]
content += [{"id": rid(), "type": "chart", "data": {"chart_name": label, "col": 6}} for _, label in STANDARD_CHARTS]
content += [{"id": rid(), "type": "number_card", "data": {"number_card_name": label, "col": 4}} for _, label in STANDARD_NUMBER_CARDS]
content += [{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Budget, Claims and Approvals</b></span>', "col": 12}}]
content += [{"id": rid(), "type": "number_card", "data": {"number_card_name": name, "col": 4}} for name, *_ in NUMBER_CARDS]
content += [{"id": rid(), "type": "chart", "data": {"chart_name": name, "col": 6}} for name, *_ in CHARTS]
content += [{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Shortcuts</b></span>', "col": 12}}]
content += [{"id": rid(), "type": "shortcut", "data": {"shortcut_name": label, "col": 3}} for label, _, _ in SHORTCUTS]
content += [
	{"id": rid(), "type": "spacer", "data": {"col": 12}},
	{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Documents and Reports</b></span>', "col": 12}},
]
content += [{"id": rid(), "type": "card", "data": {"card_name": card, "col": 4}} for card, _ in CARDS]

dump("project_management_muhick/muhick_projects/workspace/muhick_projects/muhick_projects.json", {
	**BASE, "app": "project_management_muhick",
	"charts": [{"chart_name": name, "label": label} for name, label in STANDARD_CHARTS] + [{"chart_name": name, "label": name} for name, *_ in CHARTS],
	"content": json.dumps(content, separators=(",", ":")), "custom_blocks": [], "doctype": "Workspace", "for_user": "",
	"hide_custom": 0, "icon": "project", "is_hidden": 0, "label": WS, "links": links, "module": "Muhick Projects", "name": WS,
	"number_cards": [{"label": label, "number_card_name": name} for name, label in STANDARD_NUMBER_CARDS]
	+ [{"label": name, "number_card_name": name} for name, *_ in NUMBER_CARDS], "parent_page": "", "public": 1,
	"quick_lists": [], "restrict_to_domain": "", "roles": [], "sequence_id": 30.0, "shortcuts": shortcuts, "title": WS,
	"type": "Workspace",
})


# ------------------------------------------------------------------ sidebar and desktop icons
def link(label, to, link_type="DocType", child=0, icon=None):
	d = {"child": child, "collapsible": 1, "indent": 0, "keep_closed": 0, "label": label, "link_to": to, "link_type": link_type, "show_arrow": 0, "type": "Link"}
	if icon is not None:
		d["icon"] = icon
	return d


items = [
	link("Home", WS, "Workspace", icon="home"),
	# ERPNext's Project dashboard and its own Projects page stay one click away
	link("Projects Dashboard", "Project", "Dashboard", icon="dashboard"),
	link("Projects Workspace", "Projects", "Workspace", icon="project"),
	link("Project", "Project", icon="projects"),
]
for card, entries in CARDS:
	items.append({
		"child": 0, "collapsible": 1, "icon": ICONS[card], "indent": 1, "keep_closed": 1 if card in CLOSED_SECTIONS else 0,
		"label": card, "link_type": "DocType", "show_arrow": 0, "type": "Section Break",
	})
	for label, to, kind, *filters in entries:
		if (label, to) != ("Project", "Project"):
			item = link(label, to, "Report" if kind == R else "DocType", child=1)
			if filters:
				item["filters"] = json.dumps(filters[0])
			items.append(item)
dump("project_management_muhick/workspace_sidebar/muhick_projects.json", {
	**BASE, "app": "project_management_muhick", "doctype": "Workspace Sidebar", "header_icon": "project", "items": items,
	"module": "Muhick Projects", "name": WS, "standard": 1, "title": WS,
})

LOGO = "/assets/project_management_muhick/images/muhick-logo.svg"
dump("project_management_muhick/desktop_icon/project_management_muhick.json", {
	**BASE, "app": "project_management_muhick", "doctype": "Desktop Icon", "hidden": 0, "icon_type": "App", "idx": 110, "label": "Project Management Muhick",
	"link": "/desk/muhick-projects", "link_type": "External", "logo_url": LOGO, "name": "Project Management Muhick", "roles": [], "standard": 1,
})
dump("project_management_muhick/desktop_icon/muhick_projects.json", {
	**BASE, "app": "project_management_muhick", "doctype": "Desktop Icon", "hidden": 0, "icon": "project", "icon_type": "Link", "idx": 1,
	"label": WS, "link_to": WS, "link_type": "Workspace Sidebar", "logo_url": LOGO, "name": WS, "parent_icon": "Project Management Muhick",
	"restrict_removal": 0, "roles": [], "standard": 1,
})

# ------------------------------------------------------------------ every target must exist
ours = {json.load(open(f, encoding="utf-8"))["name"] for f in glob.glob("project_management_muhick/**/doctype/*/*.json", recursive=True)}
reports = {json.load(open(f, encoding="utf-8"))["name"] for f in glob.glob("project_management_muhick/**/report/*/*.json", recursive=True)}
standard_reports = {"Project Summary", "Daily Timesheet Summary", "Timesheet Billing Summary", "Project wise Stock Tracking", "Delayed Tasks Summary"}
standard = {"Lead", "Opportunity", "Task Type", "Timesheet", "Activity Type", "Activity Cost", "Project Type", "Project Update", "Projects Settings", "Project", "Task", "Project Template", "Material Request", "Supplier Quotation", "Purchase Order", "Purchase Receipt", "Payment Request", "Payment Entry", "Vehicle"}
bad = [(label, to) for _, e in CARDS for label, to, k, *_ in e if to not in (reports | standard_reports if k == R else ours | standard)]
bad += [(label, to) for label, to, typ in SHORTCUTS if to not in (reports if typ == "Report" else ours | standard)]
bad += [(n, dt) for n, _, _, dt, _ in NUMBER_CARDS if dt not in ours | standard]
unlinked = sorted(reports - {to for _, e in CARDS for _, to, k, *_ in e if k == R})
menu_doctypes = {to for _, e in CARDS for _, to, k, *_ in e if k == D}
parents = {json.load(open(f, encoding="utf-8"))["name"] for f in glob.glob("project_management_muhick/**/doctype/*/*.json", recursive=True) if not json.load(open(f, encoding="utf-8")).get("istable")}
print("workspace links:", sum(len(e) for _, e in CARDS), "| sidebar items:", len(items), "| number cards:", len(NUMBER_CARDS), "| charts:", len(CHARTS))
print("unresolved:", bad, "| reports not on the menu:", unlinked, "| documents not on the menu:", sorted(parents - menu_doctypes))
