# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Starting values. Created once; Muhick owns and edits them afterwards."""

import frappe

# the mandatory handover pack
HANDOVER_CHECKLIST = [
	("Signed contract", 1),
	("Bill of Quantities (BOQ)", 1),
	("Technical specifications", 1),
	("Approved quotation", 1),
	("Supplier quotations used for the bid", 1),
	("Payment terms", 1),
	("Delivery period", 1),
	("Warranty terms", 1),
	("Securities (bid security, performance bond, advance guarantee)", 1),
	("Risks and assumptions", 1),
	("Technical data sheets and catalogues", 0),
	("Best Evaluated Bidder notice", 0),
]

# the budget is built in three parts: Materials, Works and Administrative
COST_CODES = [
	("MAT-100", "Materials - Plumbing", "Materials", "Materials"),
	("MAT-200", "Materials - Electrical", "Materials", "Materials"),
	("MAT-300", "Materials - Mechanical / HVAC", "Materials", "Materials"),
	("MAT-400", "Materials - Civil and Finishes", "Materials", "Materials"),
	("MAT-500", "Equipment for Installation (Pumps, Generators, Panels)", "Materials", "Materials"),
	("MAT-900", "Consumables", "Materials", "Materials"),
	("WRK-100", "Casual Labour", "Works", "Casual Labour"),
	("WRK-200", "Subcontracted Works", "Works", "Subcontract"),
	("WRK-300", "Equipment and Tools Hire", "Works", "Equipment and Tools"),
	("ADM-100", "Transport and Logistics", "Administrative", "Transport and Logistics"),
	("ADM-200", "Site Visits and Mobilization", "Administrative", "Site Expenses"),
	("ADM-300", "PPE and Site Safety", "Administrative", "Site Expenses"),
	("ADM-400", "Cost of Financing (Guarantees, LC and Bank Charges)", "Administrative", "Financing"),
	("ADM-500", "Commissions", "Administrative", "Other"),
	("ADM-900", "Other Site Expenses", "Administrative", "Site Expenses"),
]

# what a new supplier must provide before it can be approved
SUPPLIER_ONBOARDING = [
	("Certificate of registration / incorporation", 1),
	("Tax identification and tax clearance", 1),
	("Bank account details on the supplier's letterhead", 1),
	("Physical address verified (supplier visit)", 0),
	("Trading licence", 0),
	("References from previous clients", 0),
]

LABOUR_TRADES = ["Electrician", "Plumber", "Mason", "Welder", "Painter", "Carpenter", "Helper", "Machine Operator"]

# where leads come from (ERPNext's Source list, which bids use too) and the client's sector
LEAD_SOURCES = [
	("e-GP Portal", "Tenders on the government electronic procurement portal"),
	("Newspaper Advert", None),
	("Website Advert", "Adverts on government and company websites"),
	("Referral", "Referred by a person or organisation the company has worked with"),
	("Existing Customer", "A repeat client: pick the customer on the lead"),
	("Sent by Management", "Passed on by the Managing Director or the General Manager"),
	("Sales Team Prospecting", "Found by the sales team"),
	("Other", None),
]
SECTORS = ["Public Sector", "Private Sector"]


def setup_defaults():
	for code, name, section, category in COST_CODES:
		if not frappe.db.exists("Cost Code", code):
			frappe.get_doc(
				doctype="Cost Code", cost_code=code, cost_code_name=name, budget_section=section, cost_category=category
			).insert(ignore_permissions=True)

	for trade in LABOUR_TRADES:
		if not frappe.db.exists("Labour Trade", trade):
			frappe.get_doc(doctype="Labour Trade", trade_name=trade).insert(ignore_permissions=True)

	setup_lead_lists()

	settings = frappe.get_single("Muhick Settings")
	changed = False
	for table, rows in (("handover_checklist", HANDOVER_CHECKLIST), ("supplier_onboarding_checklist", SUPPLIER_ONBOARDING)):
		if not settings.get(table):
			for item, mandatory in rows:
				settings.append(table, {"checklist_item": item, "is_mandatory": mandatory})
			changed = True
	if changed:
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)


def setup_lead_lists():
	for name, description in LEAD_SOURCES:
		if not frappe.db.exists("UTM Source", name):
			frappe.get_doc(doctype="UTM Source", description=description).insert(set_name=name, ignore_permissions=True)
	for name in SECTORS:
		if not frappe.db.exists("Market Segment", name):
			frappe.get_doc(doctype="Market Segment", market_segment=name).insert(ignore_permissions=True)
