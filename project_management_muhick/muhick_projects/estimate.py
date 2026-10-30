# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid's cost estimate, and the project budget it becomes.

The estimate is built on the opportunity sheet by sheet, as the business's budget workbook: a table for
each of Equipment, Installation Materials, Freight and Clearing, Labour, Tools and Equipment,
Preliminaries and Administrative, with the very lines of a project budget (Project Budget Line), and
the tax computation of the imported goods (Import Tax Line). Each line has a stage from the shared
milestone list (the system or phase it is for), an item or a description, its supplier and brand, its
cost code, its amount as quoted and its amount in the company's currency without VAT: people x qty x
rate at the line's exchange rate (a rate quoted with VAT taken without it), or a share of the contract
value. The budget summary and profitability read like the workbook's. When the project is handed
over, the estimate becomes the project's draft budget, the tax computation as its insurance, duty and
levy, and the Project Manager adjusts it before sending it for approval. A budget line takes the
project's milestone (phase) of its stage once the activity plan has created it."""

import base64
import difflib
import io
import re
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

from project_management_muhick.muhick_projects.utils import ensure_milestone, get_phases
from project_management_muhick.muhick_sales.bids import boq_factor, boq_quotes, last_purchase_rate, latest_by_supplier, lowest, project_bid
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import get_settings, setting

# what a line carries from the estimate to the budget
LINE_FIELDS = (
	"section", "stage", "item_code", "description", "uom", "brand", "supplier", "people", "qty", "rate", "currency",
	"exchange_rate", "rate_includes_vat", "contract_percent", "cost_code", "procurement_type", "remarks",
)
SECTIONS = calc.COST_SECTIONS
# the settings a cost estimate works with, and their values until Muhick sets its own
DEFAULTS = {"vat_percent": 18, "import_insurance_percent": 1.5, "import_duty_percent": 10, "import_levy_percent": 1.5}
# the cost code a line given none takes: its item's default, else one its description points to (for labour
# and overheads), else its section's own; only codes the business has and uses are taken
SECTION_CODES = {
	"Equipment": "MAT-500", "Installation Materials": "MAT-100", "Taxes and Freight": "MAT-600", "Labour": "WRK-150",
	"Tools and Equipment": "WRK-300", "Preliminaries": "ADM-100", "Administrative": "ADM-900",
}
DESCRIPTION_CODES = (
	(r"sub[ -]?contract", "WRK-200"), (r"casual|food", "WRK-100"), (r"\bcommissions?\b", "ADM-500"),
	(r"contingen|miscell|correction of works|rework", "ADM-700"), (r"helmet|gumboot|glove|mask|jacket|safety|ppe", "ADM-300"),
	(r"per diem|site visit|relocation|handover", "ADM-200"), (r"fuel|transport|loading|car service", "ADM-100"),
)
# the opportunity's tables of estimate lines, one per section as the sheets of the budget workbook, and its tax
# computation
ESTIMATE_TABLES = {
	"muhick_equipment": "Equipment", "muhick_materials": "Installation Materials", "muhick_freight": "Taxes and Freight",
	"muhick_labour": "Labour", "muhick_tools": "Tools and Equipment", "muhick_preliminaries": "Preliminaries",
	"muhick_administrative": "Administrative",
}
TAX_TABLE = "muhick_import_taxes"
TAX_FIELDS = (
	"stage", "item_code", "description", "supplier", "country_of_origin", "mode_of_shipment", "qty", "uom", "rate", "currency",
	"exchange_rate", "insurance_percent", "duty_percent", "vat_percent", "levy_percent",
)
TAX_AMOUNTS = ("value", "insurance", "customs_value", "duty", "vat", "levy", "total_tax", "cost")


def estimate_lines(doc) -> list:
	"""An opportunity's estimate lines, table by table, each in its table's section."""
	lines = []
	for field, section in ESTIMATE_TABLES.items():
		for line in doc.get(field) or []:
			line.section = section
			lines.append(line)
	return lines


def arrange(lines):
	"""Every line in a section (from its cost code when none is given), and the lines in the order of the
	sections, keeping their order within each."""
	for line in lines:
		if not line.section and line.cost_code:
			budget_section = frappe.get_cached_value("Cost Code", line.cost_code, "budget_section")
			line.section = calc.section_of_cost_code(line.cost_code, budget_section)
	order = {section: i for i, section in enumerate(SECTIONS)}
	lines.sort(key=lambda line: (order.get(line.section, len(order)), line.idx or 0))
	for idx, line in enumerate(lines, 1):
		line.idx = idx


def propose_cost_code(section, description, item_code, enabled) -> str | None:
	"""The cost code for a line given none (see SECTION_CODES), among the enabled codes."""
	code = frappe.get_cached_value("Item", item_code, "muhick_cost_code") if item_code else None
	if code in enabled:
		return code
	if section in ("Labour", "Preliminaries", "Administrative"):
		text = (description or "").lower()
		code = next((c for pattern, c in DESCRIPTION_CODES if re.search(pattern, text)), None)
		if code in enabled:
			return code
	code = (setting("import_cost_code") if section == "Taxes and Freight" else None) or SECTION_CODES.get(section)
	return code if code in enabled else None


def propose_cost_codes(lines):
	"""A line given no cost code takes the one its item, description or section points to (see SECTION_CODES)."""
	missing = [line for line in lines if not line.cost_code]
	if missing:
		enabled = set(frappe.get_all("Cost Code", filters={"disabled": 0}, pluck="name"))
		for line in missing:
			line.cost_code = propose_cost_code(line.section, line.description, line.item_code, enabled)


def set_amounts(doc, lines, contract_value) -> float:
	"""Each line's amount as quoted and in the company's currency without VAT; returns the total of the
	latter. A line priced as a share of the contract value reads as one lot at that amount."""
	vat = flt(setting("vat_percent", DEFAULTS["vat_percent"]))
	total = 0.0
	for line in lines:
		company_currency = _check_currency(doc, line)
		line.people = line.people or 1
		line.amount = calc.line_amount(
			line.qty, line.rate, line.people, line.exchange_rate, line.rate_includes_vat, vat, line.contract_percent, contract_value
		)
		if flt(line.contract_percent):
			line.update({"qty": 1, "rate": line.amount, "people": 1, "currency": company_currency, "exchange_rate": 1, "rate_includes_vat": 0})
		line.quoted_amount = flt(line.qty) * flt(line.rate) * line.people
		total += flt(line.amount)
	return total


def set_import_taxes(doc, rows) -> float:
	"""Each imported good's taxes in its currency, as the business's tax computation works them out (see
	calc.import_taxes); returns what they cost the budget in the company's currency."""
	total = 0.0
	for row in rows:
		_check_currency(doc, row)
		row.value = flt(row.qty) * flt(row.rate)
		taxes = calc.import_taxes(row.value, row.insurance_percent, row.duty_percent, row.vat_percent, row.levy_percent)
		row.update({field: taxes[field] for field in ("insurance", "customs_value", "duty", "vat", "levy", "total_tax")})
		row.cost = taxes["cost"] * flt(row.exchange_rate)
		total += row.cost
	return total


def _check_currency(doc, row) -> str | None:
	"""A row in another currency has its exchange rate; any other is in the company's currency, named so its
	amounts show in it, at one. Returns the company's currency."""
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") if doc.get("company") else None
	if row.currency and row.currency != company_currency:
		if not flt(row.exchange_rate):
			label = _(doc.meta.get_label(row.parentfield)) if row.get("parentfield") else ""
			frappe.throw(_("{0} row {1}: give the exchange rate of {2}.").format(label, row.idx, row.currency))
	else:
		row.currency, row.exchange_rate = company_currency, 1
	return company_currency


def tax_cost_lines(rows) -> list:
	"""The budget lines a tax computation comes to: its insurance, import duty and infrastructure levy,
	stage by stage, in the company's currency (the VAT is claimed back)."""
	sums = defaultdict(float)
	for row in rows:
		for kind in ("insurance", "duty", "levy"):
			sums[(row.get("stage") or "", kind)] += flt(row.get(kind)) * (flt(row.get("exchange_rate")) or 1)
	enabled = set(frappe.get_all("Cost Code", filters={"disabled": 0}, pluck="name"))
	code = propose_cost_code("Taxes and Freight", "", None, enabled)
	labels = {"insurance": _("Insurance of the imported goods"), "duty": _("Import duty"), "levy": _("Infrastructure levy")}
	return [
		{
			"section": "Taxes and Freight", "stage": stage or None, "description": labels[kind], "qty": 1, "rate": flt(amount, 2),
			"people": 1, "exchange_rate": 1, "rate_includes_vat": 0, "cost_code": code, "procurement_type": "Not Applicable",
		}
		for (stage, kind), amount in sums.items()
		if flt(amount, 2)
	]


def resolve_stages(project, lines):
	"""A budget line's stage and milestone agree: a line placed in a milestone takes its stage from it,
	and a line with only a stage takes the project's milestone of that name once it exists."""
	if not project:
		return
	phases = {}
	for phase in get_phases(project, ("name", "type")):
		if phase.type:
			phases.setdefault(phase.type, phase.name)
	for line in lines:
		if line.phase:
			line.stage = frappe.get_cached_value("Task", line.phase, "type") or line.stage
		elif line.stage:
			line.phase = phases.get(line.stage)


def link_budget_phases(project):
	"""Once the activity plan has created the project's milestones, the budget lines that only had a
	stage take the milestone of that name."""
	frappe.db.sql(
		"""
		update `tabProject Budget Line` line
		inner join `tabProject Budget` budget on budget.name = line.parent
		inner join `tabTask` task on task.project = budget.project and task.type = line.stage
		set line.phase = task.name
		where line.parenttype = 'Project Budget' and budget.project = %(project)s and budget.docstatus < 2
			and ifnull(line.phase, '') = '' and ifnull(line.stage, '') != ''
			and task.is_group = 1 and ifnull(task.parent_task, '') = '' and task.status != 'Cancelled'
		""",
		{"project": project},
	)


# ------------------------------------------------------------------ building the estimate on the opportunity
@frappe.whitelist()
def get_estimate_settings() -> dict:
	"""The VAT rate taken out of rates quoted with it, and the rates and cost code of import costs."""
	values = {field: flt(setting(field, default)) for field, default in DEFAULTS.items()}
	values["import_cost_code"] = get_settings().get("import_cost_code")
	return values


def supplier_price(quotes, item_code, uom, company_currency) -> dict | None:
	"""The lowest valid quotation among an item's quotes, per unit of uom, in the quotation's own
	currency and at its exchange rate; None when no supplier has quoted it."""
	best = lowest(list(latest_by_supplier(quotes).values()))
	if not best:
		return None
	foreign = best.currency and best.currency != company_currency
	return {
		"supplier": best.supplier,
		"currency": best.currency if foreign else None,
		"exchange_rate": flt(best.conversion_rate) if foreign else 1,
		"rate": best.price * boq_factor(item_code, uom),
	}


@frappe.whitelist()
def get_boq_lines(opportunity: str, items) -> list:
	"""Estimate lines for BOQ items ([item_code, uom, qty, stage] each): the item at the lowest valid
	supplier quotation for the bid, or else at its last purchase price, with its brand and cost code, in
	the section its cost code gives (equipment for MAT-500, else installation materials)."""
	bid = frappe.get_doc("Opportunity", opportunity)
	bid.check_permission("write")
	company_currency = frappe.get_cached_value("Company", bid.company, "default_currency")
	quotes = boq_quotes(opportunity)
	rows = []
	for item_code, uom, qty, stage in frappe.parse_json(items):
		info = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom", "brand", "muhick_cost_code"], as_dict=True)
		if not info:
			continue
		uom = uom or info.stock_uom
		section = calc.section_of_cost_code(info.muhick_cost_code) if info.muhick_cost_code else None
		row = {
			"section": section if section in ("Equipment", "Tools and Equipment") else "Installation Materials",
			"stage": stage, "item_code": item_code, "description": info.item_name, "uom": uom, "qty": flt(qty) or 1,
			"brand": info.brand, "cost_code": info.muhick_cost_code, "people": 1, "exchange_rate": 1,
		}
		row.update(
			supplier_price(quotes.get(item_code, []), item_code, uom, company_currency)
			or {"rate": last_purchase_rate(item_code) * boq_factor(item_code, uom)}
		)
		rows.append(row)
	return rows


@frappe.whitelist()
def get_item_price(item_code: str, uom: str | None = None, opportunity: str | None = None, company: str | None = None) -> dict:
	"""The price a line of an item from the item master starts at, per unit of uom: the lowest valid supplier
	quotation for the bid, else the item's last purchase price; {} when there is none."""
	frappe.has_permission("Item", "read", throw=True)
	if opportunity:
		bid = frappe.get_doc("Opportunity", opportunity)
		bid.check_permission("read")
		company = bid.company
	company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	price = supplier_price(boq_quotes(opportunity).get(item_code, []), item_code, uom, company_currency) if opportunity else None
	if price:
		return {**price, "currency": price["currency"] or company_currency}
	rate = flt(last_purchase_rate(item_code)) * boq_factor(item_code, uom)
	return {"rate": rate, "currency": company_currency, "exchange_rate": 1} if rate else {}


@frappe.whitelist()
def get_supplier_prices(opportunity: str, items) -> dict:
	"""{"item_code|uom": price} at the lowest valid supplier quotation for the bid, for the items
	([item_code, uom] each) a supplier has quoted."""
	bid = frappe.get_doc("Opportunity", opportunity)
	bid.check_permission("write")
	company_currency = frappe.get_cached_value("Company", bid.company, "default_currency")
	quotes = boq_quotes(opportunity)
	prices = {}
	for item_code, uom in frappe.parse_json(items):
		price = supplier_price(quotes.get(item_code, []), item_code, uom, company_currency)
		if price:
			prices[f"{item_code}|{uom or ''}"] = price
	return prices


# ------------------------------------------------------------------ from the estimate to the budget
def estimate_rows(opportunity) -> list:
	"""The bid's cost estimate, sheet by sheet and line by line, and the insurance, duty and levy of its tax
	computation, ready to become budget lines."""
	lines = frappe.get_all(
		"Project Budget Line",
		filters={"parent": opportunity, "parenttype": "Opportunity", "parentfield": ("in", list(ESTIMATE_TABLES))},
		fields=["parentfield", "idx", *LINE_FIELDS],
	)
	order = {field: i for i, field in enumerate(ESTIMATE_TABLES)}
	lines.sort(key=lambda line: (order[line.parentfield], line.idx))
	rows = [{**{f: line.get(f) for f in LINE_FIELDS}, "section": ESTIMATE_TABLES[line.parentfield]} for line in lines]
	taxes = frappe.get_all(
		"Import Tax Line",
		filters={"parent": opportunity, "parenttype": "Opportunity", "parentfield": TAX_TABLE},
		fields=["stage", "exchange_rate", "insurance", "duty", "levy"],
		order_by="idx asc",
	)
	return rows + tax_cost_lines(taxes)


@frappe.whitelist()
def get_estimate_lines(project: str) -> list:
	"""The cost estimate of the bid a project came from, as budget lines placed in the project's
	milestones where it has them."""
	frappe.has_permission("Project Budget", "write", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	opportunity = project_bid(project)
	rows = estimate_rows(opportunity) if opportunity else []
	if not rows:
		frappe.throw(_("Project {0} did not come from a bid with a cost estimate.").format(project))
	lines = [frappe._dict(row) for row in rows]
	resolve_stages(project, lines)
	return lines


def make_budget(handover):
	"""At an accepted handover, the bid's cost estimate becomes the project's draft budget, assigned
	to the receiving Project Manager to adjust and send for approval. Nothing is made for a project
	that already has a budget, or from a bid without an estimate."""
	project = handover.project
	if not handover.opportunity or frappe.db.exists("Project Budget", {"project": project, "docstatus": ("<", 2)}):
		return None
	rows = estimate_rows(handover.opportunity)
	if not rows:
		return None
	budget = frappe.new_doc("Project Budget")
	budget.update(
		{
			"project": project,
			"company": handover.company,
			"prepared_by": handover.project_manager,
			"boq": frappe.db.get_value("Project", project, "muhick_boq"),
			"remarks": _("From the cost estimate of bid {0}.").format(handover.opportunity),
		}
	)
	for row in rows:
		budget.append("lines", row)
	budget.flags.ignore_permissions = True
	budget.insert()
	try:
		from frappe.desk.form.assign_to import add as assign

		assign(
			{
				"assign_to": [handover.project_manager],
				"doctype": "Project Budget",
				"name": budget.name,
				"description": _("Adjust the budget made from the bid's cost estimate, then send it for approval."),
			}
		)
	except Exception:
		frappe.log_error(title=f"Muhick: could not assign budget {budget.name}")
	frappe.msgprint(
		_("Draft budget {0} was made from the bid's cost estimate. Adjust it, then send it for approval.").format(
			frappe.utils.get_link_to_form("Project Budget", budget.name)
		),
		alert=True,
	)
	return budget.name


# ------------------------------------------------------------------ the Budget Summary print
def budget_summary(doc) -> dict:
	"""For the Budget Summary print, laid out as the business's budget summary: each section (A Equipment,
	B Installation Materials...) against the stages, in the order of the project's milestones and with
	their months, then the cost codes, the contract value and the margin."""
	lines = doc.get("lines") or []
	milestones = {}
	for phase in get_phases(doc.project, ("name", "type", "subject", "exp_start_date", "exp_end_date")) if doc.get("project") else []:
		milestones.setdefault(phase.type or phase.subject, phase)
	stages = [s for s in milestones if any((line.stage or "") == s for line in lines)]
	stages += [s for s in dict.fromkeys(line.stage or "" for line in lines) if s not in stages and s]
	if any(not line.stage for line in lines):
		stages.append("")
	cells, by_code = defaultdict(float), defaultdict(float)
	for line in lines:
		cells[(line.section or "", line.stage or "")] += flt(line.amount)
		by_code[line.cost_code] += flt(line.amount)
	present = [s for s in [*SECTIONS, ""] if any(section == s for section, _stage in cells)]
	sections = []
	for letter, section in zip("ABCDEFGHIJ", present):
		values = [cells[(section, stage)] for stage in stages]
		sections.append({"letter": letter, "section": _(section) if section else _("Other"), "amounts": values, "total": sum(values)})
	totals = [sum(cells[(section, stage)] for section in present) for stage in stages]
	contract = flt(doc.get("contract_value"))
	total = sum(totals)
	current = flt(doc.get("total_current_budget")) or total
	return {
		"stages": [{"name": s, "period": _period(milestones.get(s))} for s in stages],
		"sections": sections,
		"amounts": totals,
		"total": total,
		"cost_codes": [
			{"cost_code": code, "name": frappe.get_cached_value("Cost Code", code, "cost_code_name") or "", "amount": amount}
			for code, amount in sorted(by_code.items()) if code
		],
		"variations": flt(doc.get("total_approved_variations")),
		"current": current,
		"contract_value": contract,
		"margin": contract - current if contract else 0,
		"margin_percent": calc.margin_percent(contract, current),
	}


def _period(phase) -> str:
	"""A milestone's months: Oct 2026, or Sep - Oct 2026."""
	if not phase or not phase.exp_start_date:
		return ""
	start, end = getdate(phase.exp_start_date), getdate(phase.exp_end_date or phase.exp_start_date)
	if (start.year, start.month) == (end.year, end.month):
		return formatdate(start, "MMM yyyy")
	return f"{formatdate(start, 'MMM yyyy' if start.year != end.year else 'MMM')} - {formatdate(end, 'MMM yyyy')}"


# ------------------------------------------------------------------ to and from Excel
# an estimate or budget prepared in Excel comes in through the workbook the system gives out, laid out as the
# business's budget sheets (a sheet per section, one row per line, and the tax computation), or through the
# business's own workbook
TABLES = {"Opportunity": [*ESTIMATE_TABLES, TAX_TABLE], "Project Budget": ["lines"]}
EXCEL_COLUMNS = (
	# "Item Code", not "Item": budget sheets often number their rows in an Item column
	("stage", "Stage"), ("item_code", "Item Code"), ("description", "Description"), ("uom", "UOM"), ("brand", "Brand"),
	("supplier", "Supplier"), ("people", "People"), ("qty", "Qty"), ("rate", "Rate"), ("currency", "Currency"),
	("exchange_rate", "Exchange Rate"), ("rate_includes_vat", "Rate Includes VAT"), ("contract_percent", "% of Contract Value"),
	("cost_code", "Cost Code"), ("procurement_type", "Procurement Type"), ("remarks", "Remarks"),
)
# other headings budget sheets use for the same columns
HEADING_ALIASES = {
	"section": "section", "milestone": "stage", "phase": "stage", "system": "stage", "details": "description",
	"itemdescription": "description", "unit": "uom", "quantity": "qty", "vatinclusive": "rate_includes_vat",
	"includesvat": "rate_includes_vat", "comments": "remarks", "contractvalue": "contract_percent",
}
# sheet names and heading rows that name a section, as the business's budget sheets write them
SECTION_NAMES = {
	"equipment": "Equipment", "installationequipment": "Equipment",
	"installationmaterials": "Installation Materials", "materials": "Installation Materials",
	"taxesandfreight": "Taxes and Freight", "taxes": "Taxes and Freight", "taxcomputation": "Taxes and Freight",
	"taxcomputations": "Taxes and Freight", "importcosts": "Taxes and Freight", "freightandclearing": "Taxes and Freight",
	"labour": "Labour", "labor": "Labour", "labourrequirement": "Labour", "labourrequirements": "Labour",
	"toolsandequipment": "Tools and Equipment", "toolsequipment": "Tools and Equipment", "tools": "Tools and Equipment",
	"preliminaries": "Preliminaries",
	"administrative": "Administrative", "administrativecosts": "Administrative", "admin": "Administrative",
}
# units as budget sheets write them, for the units of the unit list
UNIT_ALIASES = {
	"pcs": "Nos", "pce": "Nos", "no": "Nos", "number": "Nos", "piece": "Nos", "pieces": "Nos",
	"m": "Meter", "meters": "Meter", "metres": "Meter", "ltrs": "Litre", "litres": "Litre", "liters": "Litre",
	"days": "Day", "weeks": "Week", "hours": "Hour", "hrs": "Hour", "pairs": "Pair", "sets": "Set", "boxes": "Box",
}
# other units budget sheets write, telling a unit from a brand in a row laid out unlike its heading row
UNIT_WORDS = ("month", "months", "lump", "lumpsum", "ls", "item", "items", "trip", "trips", "bag", "bags", "packet", "packets", "roll", "lot")
# the columns of a tax computation, as the business's Taxes sheet and the Tax Computation sheet given out here
# head them
TAX_HEADINGS = {
	"total": "value", "insurance": "insurance", "ci": "customs_value", "customsvalue": "customs_value", "id": "duty",
	"importduty": "duty", "vat": "vat", "il": "levy", "infrastructurelevy": "levy", "totaltax": "total_tax",
	"insurancerate": "insurance_percent", "dutyrate": "duty_percent", "vatrate": "vat_percent", "levyrate": "levy_percent",
	"countryoforigin": "country_of_origin", "modeofshipment": "mode_of_shipment",
}
TAX_EXCEL_COLUMNS = (
	("stage", "Stage"), ("item_code", "Item Code"), ("description", "Description"), ("supplier", "Supplier"), ("country_of_origin", "Country of Origin"),
	("mode_of_shipment", "Mode of Shipment"), ("qty", "Qty"), ("uom", "UOM"), ("rate", "Rate"), ("currency", "Currency"),
	("exchange_rate", "Exchange Rate"), ("insurance_percent", "Insurance Rate %"), ("duty_percent", "Duty Rate %"),
	("vat_percent", "VAT Rate %"), ("levy_percent", "Levy Rate %"),
)
SHIPMENT_MODES = ("Sea Freight", "Air Freight", "Road Freight", "Sea and Air Freight")
PROCUREMENT_TYPES = ("Local", "International", "From Stock", "Not Applicable")
YES = ("yes", "y", "true", "1", "x")
# a heading's numbering (A., 1., 1.2), a sheet or heading naming a phase (Phase 1), and a share of the contract
# value written in a description (Miscellaneous, 1% of contract amount)
NUMBERING = re.compile(r"^\s*(?:\d+(?:\.\d+)+\.?|\d+[.)]|[A-Za-z][.)])\s+")
PHASE_WORDS = ("phase", "stage", "milestone", "lot")
CONTRACT_SHARE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s+(?:the\s+)?contract", re.IGNORECASE)
# costs a budget sheet may give as an amount alone, without a qty or rate (TAXES, FREIGHT CHARGES)
LUMP_SUMS = re.compile(r"\b(?:tax|taxes|duty|duties|levy|freight|insurance|clearing)\b", re.IGNORECASE)


def _cost_doc(doctype, name, ptype):
	"""The estimate or budget the lines belong to, once the user may read or change it; None while unsaved."""
	if doctype not in TABLES:
		frappe.throw(_("Cost lines belong to an opportunity or a project budget."))
	if not name:
		frappe.has_permission(doctype, "create" if ptype == "write" else "read", throw=True)
		return None
	doc = frappe.get_doc(doctype, name)
	doc.check_permission(ptype)
	return doc


@frappe.whitelist()
def download_cost_lines(doctype: str, name: str | None = None):
	"""A workbook of an estimate's or a budget's lines to prepare or change in Excel and upload again: a sheet
	per section, as in the business's budget sheets, each line's amount worked out as on screen, an
	estimate's tax computation with its formulas, and lists to pick the stage, cost code, currency,
	procurement type, VAT, country and shipment from, on a sheet of their own."""
	from openpyxl import Workbook

	doc = _cost_doc(doctype, name, "read")
	lines = _doc_lines(doctype, doc)
	book = Workbook()
	book.remove(book.active)
	lists = _lists(book)
	vat = flt(setting("vat_percent", DEFAULTS["vat_percent"]))
	unplaced = [line for line in lines if line.section not in SECTIONS]
	for section in [*SECTIONS, *(["Other"] if unplaced else [])]:
		if section == "Taxes and Freight" and doctype == "Opportunity":
			_tax_sheet(book, doc.get(TAX_TABLE) if doc else [], lists)
		own = unplaced if section == "Other" else [line for line in lines if line.section == section]
		_lines_sheet(book, section, own, vat, lists)
	book.move_sheet("Lists", offset=len(book.sheetnames))
	out = io.BytesIO()
	book.save(out)
	frappe.response["filename"] = f"{name or _(doctype)} - Cost Lines.xlsx"
	frappe.response["filecontent"] = out.getvalue()
	frappe.response["type"] = "binary"


def _lists(book) -> dict:
	"""The Lists sheet; {field: its range on the sheet} for the columns that pick from a list."""
	from openpyxl.styles import Font

	sheet = book.create_sheet("Lists")
	codes = frappe.get_all("Cost Code", filters={"disabled": 0}, fields=["name", "cost_code_name"], order_by="name asc")
	columns = {
		"stage": ("A", ["Stage", *frappe.get_all("Task Type", pluck="name", order_by="name asc")]),
		"cost_code": ("B", ["Cost Code", *[c.name for c in codes]]),
		"cost_code_name": ("C", ["Description", *[c.cost_code_name for c in codes]]),
		"section": ("D", ["Section", *[calc.section_of_cost_code(c.name) or "" for c in codes]]),
		"currency": ("E", ["Currency", *frappe.get_all("Currency", filters={"enabled": 1}, pluck="name", order_by="name asc")]),
		"procurement_type": ("F", ["Procurement Type", *PROCUREMENT_TYPES]),
		"rate_includes_vat": ("G", ["Rate Includes VAT", "Yes", "No"]),
		"country_of_origin": ("H", ["Country of Origin", *frappe.get_all("Country", pluck="name", order_by="name asc")]),
		"mode_of_shipment": ("I", ["Mode of Shipment", *SHIPMENT_MODES]),
	}
	for column, values in columns.values():
		for r, value in enumerate(values, 1):
			sheet[f"{column}{r}"] = value
		sheet[f"{column}1"].font = Font(bold=True)
		sheet.column_dimensions[column].width = 40 if column == "C" else 22
	return {field: f"Lists!${column}$2:${column}${max(len(values), 2)}" for field, (column, values) in columns.items()}


def _lines_sheet(book, title, lines, vat, lists):
	from openpyxl.styles import Font
	from openpyxl.worksheet.datavalidation import DataValidation

	sheet = book.create_sheet(title)
	sheet.append([heading for _field, heading in EXCEL_COLUMNS] + ["Amount"])
	for line in lines:
		sheet.append([(_yes(line.get(f)) if f == "rate_includes_vat" else line.get(f)) for f, _heading in EXCEL_COLUMNS])
	last = len(lines) + 200
	for r in range(2, last + 1):
		# G people, H qty, I rate, K exchange rate, L rate includes VAT, M % of contract value
		sheet[f"Q{r}"] = (
			f'=IF(N(M{r})>0,"",IF(N(G{r})>0,G{r},1)*N(H{r})*N(I{r})*IF(N(K{r})>0,K{r},1)'
			f'/IF(UPPER(L{r})="YES",1+{vat}/100,1))'
		)
		for column in "HIKQ":
			sheet[f"{column}{r}"].number_format = "#,##0.00"
	for cell in sheet[1]:
		cell.font = Font(bold=True)
	sheet.freeze_panes = "A2"
	for column, width in zip("ABCDEFGHIJKLMNOPQ", (22, 18, 40, 8, 14, 22, 8, 10, 14, 9, 12, 10, 12, 12, 16, 24, 16)):
		sheet.column_dimensions[column].width = width
	for column, field in (("A", "stage"), ("N", "cost_code"), ("J", "currency"), ("O", "procurement_type"), ("L", "rate_includes_vat")):
		rule = DataValidation(type="list", formula1=lists[field], allow_blank=True)
		rule.add(f"{column}2:{column}{last}")
		sheet.add_data_validation(rule)


def _tax_sheet(book, rows, lists):
	"""The Tax Computation sheet, as the business's Taxes sheet: each imported good with its rates, and its
	total, insurance, customs value (C.I), import duty (ID), VAT, levy (IL) and total tax as formulas."""
	from openpyxl.styles import Font
	from openpyxl.utils import get_column_letter
	from openpyxl.worksheet.datavalidation import DataValidation

	sheet = book.create_sheet("Tax Computation")
	sheet.append([heading for _field, heading in TAX_EXCEL_COLUMNS] + ["Total", "Insurance", "C.I", "ID", "VAT", "IL", "Total Tax"])
	for row in rows:
		sheet.append([row.get(f) for f, _heading in TAX_EXCEL_COLUMNS])
	at = {field: get_column_letter(i) for i, (field, _heading) in enumerate(TAX_EXCEL_COLUMNS, 1)}
	total, insurance, customs, duty, vat, levy, tax = (get_column_letter(len(TAX_EXCEL_COLUMNS) + i) for i in range(1, 8))
	last = len(rows) + 100
	for r in range(2, last + 1):
		formulas = {
			total: f"N({at['qty']}{r})*N({at['rate']}{r})",
			insurance: f"{total}{r}*N({at['insurance_percent']}{r})/100",
			customs: f"{total}{r}+{insurance}{r}",
			duty: f"{customs}{r}*N({at['duty_percent']}{r})/100",
			vat: f"({customs}{r}+{duty}{r})*N({at['vat_percent']}{r})/100",
			levy: f"{customs}{r}*N({at['levy_percent']}{r})/100",
			tax: f"{duty}{r}+{vat}{r}+{levy}{r}",
		}
		for column, formula in formulas.items():
			sheet[f"{column}{r}"] = f"={formula}"
		for column in (at["rate"], at["exchange_rate"], *formulas):
			sheet[f"{column}{r}"].number_format = "#,##0.00"
	for cell in sheet[1]:
		cell.font = Font(bold=True)
	sheet.freeze_panes = f"{at['supplier']}2"
	widths = {"stage": 22, "item_code": 18, "description": 40, "supplier": 22, "country_of_origin": 16, "mode_of_shipment": 16}
	for field, column in at.items():
		sheet.column_dimensions[column].width = widths.get(field, 10)
	for column in (total, insurance, customs, duty, vat, levy, tax):
		sheet.column_dimensions[column].width = 14
	for field in ("stage", "country_of_origin", "mode_of_shipment", "currency"):
		rule = DataValidation(type="list", formula1=lists[field], allow_blank=True)
		rule.add(f"{at[field]}2:{at[field]}{last}")
		sheet.add_data_validation(rule)


def _doc_lines(doctype, doc) -> list:
	"""The estimate's or budget's lines, each in its section."""
	if not doc:
		return []
	return estimate_lines(doc) if doctype == "Opportunity" else list(doc.get("lines") or [])


@frappe.whitelist()
def read_cost_lines(doctype: str, filename: str, content: str, name: str | None = None, company: str | None = None) -> dict:
	"""The cost lines of an uploaded Excel (.xlsx or .xls) or CSV file, checked row by row: {rows, tax_rows,
	errors, notes}. Every sheet with a heading row (Description or Item Code, and Qty, Rate or % of Contract
	Value) is read: the workbook downloaded from here, and the business's own budget sheets.

	A line's section is its Section column, else the heading row above it naming one (PRELIMINARIES,
	LABOUR REQUIREMENT...), else its sheet's name (Equipment, Labour...). Its stage is its Stage column,
	else its sheet's when the sheet is a phase (Phase 1) or named after a milestone, else the heading above
	it naming a system (SOLAR WATER HEATING): the milestone of that name or nearly, else a new one for the
	milestone list. In Labour, a No column is the number of people. A row laid out unlike its heading row,
	as a labour block copied under the materials headings, is read from what its cells hold, as its own
	amount bears out. A tax computation (the Taxes sheet, or the Tax Computation sheet given out here)
	comes in good by good with its rates, each in the stage of the line of its description, and its
	freight as lines; a budget, which has no tax computation, takes its insurance, duty and levy as lines.
	Other rows without a qty, rate or percentage are headings or totals. A line given no cost code is
	proposed one; a sheet without a Rate Includes VAT column has local equipment, materials and tools
	quoted with VAT. With any error nothing is taken, so the file can be corrected and uploaded again."""
	doc = _cost_doc(doctype, name, "write")
	lists = {
		doctype_: {n.lower(): n for n in frappe.get_all(doctype_, pluck="name")}
		for doctype_ in ("Task Type", "Currency", "UOM", "Brand", "Country")
	}
	milestones = _stage_index(lists["Task Type"].values())
	settings = get_estimate_settings()
	tax_defaults = {
		"insurance_percent": settings["import_insurance_percent"], "duty_percent": settings["import_duty_percent"],
		"vat_percent": settings["vat_percent"], "levy_percent": settings["import_levy_percent"],
	}
	raw, goods, skipped = [], [], 0
	for sheet, rows in _read_sheets(filename, base64.b64decode(content.split(",", 1)[-1])):
		found = _sheet_lines(sheet, rows, milestones, set(lists["UOM"]), tax_defaults)
		raw += found["lines"]
		goods += found["goods"]
		skipped += found["skipped"]
	if not raw and not goods:
		return {
			"rows": [], "tax_rows": [], "notes": [],
			"errors": [_("No cost lines found. A sheet needs a heading row naming Description, Qty and Rate, as in the Excel file downloaded from here.")],
		}

	# the stages named in the file, as milestones of the list; those not in it are added when the user may
	everything = [values for _where, values, _given in raw + goods]
	stage_texts = Counter(_text(v.get("stage")) for v in everything if _text(v.get("stage")))
	stages = {text: _match_stage(text, milestones) for text in stage_texts}
	new_stages = _new_stages({text: count for text, count in stage_texts.items() if not stages[text]})
	may_add_stages = frappe.has_permission("Task Type", "create")
	if may_add_stages:
		stages.update(new_stages)

	wanted = lambda field: {_text(v.get(field)) for v in everything if _text(v.get(field))}  # noqa: E731
	# a line names its item by its code or name, or else is linked to the item its description names
	items = _named("Item", wanted("item_code") | wanted("description"), "item_name")
	suppliers = _named("Supplier", wanted("supplier"), "supplier_name")
	codes, budget_sections = {}, {}
	for code in frappe.get_all("Cost Code", filters={"disabled": 0}, fields=["name", "cost_code_name", "budget_section"]):
		codes[code.name.lower()] = code.name
		codes.setdefault((code.cost_code_name or "").lower(), code.name)
		budget_sections[code.name] = code.budget_section
	enabled = set(budget_sections)
	company = doc.company if doc else company
	company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	errors, rows, unknown = [], [], defaultdict(set)
	proposed = vat_assumed = unplaced = shares = linked = 0
	for where, values, vat_given in raw:
		row, problems, extra = {"people": 1}, [], []
		section_text = _text(values.get("section"))
		row["section"] = SECTION_NAMES.get(_key(section_text)) if section_text else None
		if section_text and not row["section"]:
			problems.append(_("section {0} is not one of {1}").format(section_text, ", ".join(SECTIONS)))
		item = _text(values.get("item_code"))
		if item and not items.get(item.lower()):
			problems.append(_("item {0} is not in the item list").format(item))
		row["item_code"] = items.get(item.lower()) if item else items.get(_text(values.get("description")).lower())
		linked += bool(row["item_code"] and not item)
		row["stage"] = stages.get(_text(values.get("stage")))
		row["description"] = _text(values.get("description")) or (
			frappe.get_cached_value("Item", row["item_code"], "item_name") if row["item_code"] else ""
		)
		if not row["description"]:
			problems.append(_("give an item or a description"))
		row["uom"] = _unit(values, lists, unknown)
		for field, records, label in (("brand", lists["Brand"], _("Brand")), ("supplier", suppliers, _("Supplier"))):
			value = _text(values.get(field))
			row[field] = records.get(value.lower()) if value else None
			if value and not row[field]:
				unknown[_("Not in the {0} list, kept in the remarks").format(label.lower())].add(value)
				extra.append(f"{label}: {value}")
		problems += _numbers(values, row, ("people", "qty", "rate", "exchange_rate", "contract_percent"))
		share = CONTRACT_SHARE.search(row["description"]) if not row.get("rate") and not row.get("contract_percent") else None
		if share:
			row["contract_percent"] = flt(share.group(1))
			shares += 1
		row["people"] = int(row["people"]) or 1
		row["qty"] = row.get("qty", 1) if not row.get("contract_percent") else 1
		problems += _currency(values, row, lists, company_currency)
		code = _text(values.get("cost_code"))
		if code:
			row["cost_code"] = codes.get(code.lower())
			if not row["cost_code"]:
				problems.append(_("cost code {0} is not in the cost code list").format(code))
		if not row["section"] and row.get("cost_code"):
			row["section"] = calc.section_of_cost_code(row["cost_code"], budget_sections.get(row["cost_code"]))
		if not row["section"]:
			# a block of lines under no section heading, on a sheet not named after one; imported goods are equipment
			row["section"] = "Equipment" if row.get("currency") else "Installation Materials"
			unplaced += 1
		if not code:
			row["cost_code"] = propose_cost_code(row["section"], row["description"], row["item_code"], enabled)
			if row["cost_code"]:
				proposed += 1
			else:
				problems.append(_("give a cost code"))
		if vat_given:
			row["rate_includes_vat"] = 1 if _text(values.get("rate_includes_vat")).lower() in YES else 0
		else:
			row["rate_includes_vat"] = calc.rate_includes_vat_by_default(row["section"], bool(row.get("currency")))
			vat_assumed += row["rate_includes_vat"]
		kind = _text(values.get("procurement_type"))
		row["procurement_type"] = next((k for k in PROCUREMENT_TYPES if k.lower() == kind.lower()), None) if kind else None
		if kind and not row["procurement_type"]:
			problems.append(_("procurement type {0} is not one of {1}").format(kind, ", ".join(PROCUREMENT_TYPES)))
		row["remarks"] = "; ".join(filter(None, [_text(values.get("remarks")), *extra])) or None
		if problems:
			errors.append(f"{where}: {'; '.join(problems)}")
		rows.append(row)

	# the tax computation's goods, each in the stage of the line of its description when it names none
	staged = {_key(r["description"]): r["stage"] for r in rows if r.get("stage")}
	tax_rows = []
	for where, values, _given in goods:
		row = {"description": _text(values.get("description"))}
		item = _text(values.get("item_code"))
		row["item_code"] = items.get((item or row["description"]).lower())
		if item and not row["item_code"]:
			unknown[_("Imported goods: not in the item list, left without an item")].add(item)
		row["stage"] = stages.get(_text(values.get("stage"))) or _staged(row["description"], staged)
		row["uom"] = _unit(values, lists, unknown)
		supplier, country, mode = (_text(values.get(f)) for f in ("supplier", "country_of_origin", "mode_of_shipment"))
		row["supplier"] = suppliers.get(supplier.lower()) if supplier else None
		row["country_of_origin"] = lists["Country"].get(country.lower()) if country else None
		row["mode_of_shipment"] = next((m for m in SHIPMENT_MODES if m.lower() == mode.lower()), None) if mode else None
		for value, found, label in ((supplier, row["supplier"], _("supplier")), (country, row["country_of_origin"], _("country"))):
			if value and not found:
				unknown[_("Imported goods: not in the {0} list, left blank").format(label)].add(value)
		problems = _numbers(values, row, ("qty", "rate", "exchange_rate", *tax_defaults))
		row["qty"] = row.get("qty", 1)
		problems += _currency(values, row, lists, company_currency)
		if problems:
			errors.append(f"{where}: {'; '.join(problems)}")
		tax_rows.append(row)

	# a row in a currency without a rate takes the rate its currency has elsewhere in the file, else on the
	# lines already here, else today's rate
	given, used, today_rates = {}, {}, {}
	for row in rows + tax_rows:
		if row.get("currency") and flt(row.get("exchange_rate")):
			given.setdefault(row["currency"], row["exchange_rate"])
	for line in [*_doc_lines(doctype, doc), *((doc.get(TAX_TABLE) or []) if doc and doctype == "Opportunity" else [])]:
		if line.currency and flt(line.exchange_rate):
			used.setdefault(line.currency, line.exchange_rate)
	for row in rows + tax_rows:
		if not row.get("currency"):
			row["exchange_rate"] = 1
		elif not flt(row.get("exchange_rate")):
			currency = row["currency"]
			if currency not in given and currency not in used and currency not in today_rates:
				from erpnext.setup.utils import get_exchange_rate

				today_rates[currency] = flt(get_exchange_rate(currency, company_currency)) if company_currency else 0
			row["exchange_rate"] = given.get(currency) or used.get(currency) or today_rates.get(currency)
	missing = sorted({r["currency"] for r in rows + tax_rows if r.get("currency") and not flt(r.get("exchange_rate"))})
	errors += [_("Give the exchange rate of {0} on at least one of its rows.").format(c) for c in missing]
	if errors:
		more = [_("... and {0} more.").format(len(errors) - 40)] if len(errors) > 40 else []
		return {"rows": [], "tax_rows": [], "errors": errors[:40] + more, "notes": []}

	notes = [f"{label}: {', '.join(sorted(values))}" for label, values in unknown.items()]
	for row in tax_rows:
		row["value"] = flt(row["qty"]) * flt(row.get("rate"))
		taxes = calc.import_taxes(row["value"], *(row.get(f) for f in tax_defaults))
		row.update({field: flt(taxes[field], 2) for field in ("insurance", "customs_value", "duty", "vat", "levy", "total_tax")})
		row["cost"] = flt(taxes["cost"] * flt(row["exchange_rate"]), 2)
	if doctype != "Opportunity" and tax_rows:
		# a budget has no tax computation: what it comes to is lines of insurance, duty and levy
		rows += tax_cost_lines(tax_rows)
		vat = defaultdict(float)
		for row in tax_rows:
			vat[row.get("currency") or company_currency] += flt(row["vat"])
		notes += [
			_("The import VAT of {0} {1} was left out, as it is claimed back.").format(f"{amount:,.2f}", currency)
			for currency, amount in vat.items() if flt(amount)
		]
		tax_rows = []
	added = sorted({ensure_milestone(n) for n in new_stages.values()}) if may_add_stages else []
	if added:
		notes.append(_("Stages added to the milestone list: {0}").format(", ".join(added)))
	elif new_stages:
		notes.append(_("Not in the milestone list, so their lines have no stage: {0}").format(", ".join(sorted(set(new_stages.values())))))
	if unplaced:
		notes.append(_("{0} line(s) under no section heading were put in Installation Materials, or Equipment when priced in another currency; check them.").format(unplaced))
	if proposed:
		notes.append(_("{0} line(s) had no cost code and were given one from their item, description or section; check them.").format(proposed))
	if vat_assumed:
		notes.append(_("{0} local equipment, materials and tools line(s) were taken as quoted with VAT, as the budget sheets have them.").format(vat_assumed))
	if shares:
		notes.append(_("{0} line(s) were priced as the share of the contract value their description gives.").format(shares))
	if linked:
		notes.append(_("{0} line(s) were linked to the item of the item master their description names.").format(linked))
	unlinked = sum(1 for row in rows if not row.get("item_code"))
	if unlinked:
		notes.append(
			_("{0} line(s) have no item yet: pick each one's item or service from the item master in its Item / Service column, adding it to the item master first where it is missing.").format(unlinked)
		)
	if tax_rows:
		notes.append(_("{0} imported good(s) came into the tax computation with their rates.").format(len(tax_rows)))
	notes += [
		_("{0} lines are at today's rate of {1}; change it on one line and the others follow.").format(c, flt(r, 2))
		for c, r in today_rates.items() if r
	]
	if skipped:
		notes.append(_("{0} row(s) without a qty, rate or percentage were skipped as headings or totals.").format(skipped))
	return {
		"rows": [{f: row.get(f) for f in LINE_FIELDS} for row in rows],
		"tax_rows": [{f: row.get(f) for f in (*TAX_FIELDS, *TAX_AMOUNTS)} for row in tax_rows],
		"errors": [],
		"notes": notes,
	}


def _unit(values, lists, unknown):
	"""The unit list's unit an uploaded row names, as such or as budget sheets write it; None for none."""
	unit = _text(values.get("uom"))
	if not unit:
		return None
	found = lists["UOM"].get(unit.lower()) or lists["UOM"].get(UNIT_ALIASES.get(unit.lower().rstrip("."), "").lower())
	if not found:
		unknown[_("Units not in the unit list, left blank")].add(unit)
	return found


def _numbers(values, row, fields) -> list:
	"""The numbers of an uploaded row put on the line; the problems of those that are not."""
	problems = []
	for field in fields:
		value = values.get(field)
		if _text(value):
			number = _number(value)
			if number is None:
				problems.append(_("{0} is not a number").format(value))
			else:
				row[field] = number
	return problems


def _currency(values, row, lists, company_currency) -> list:
	"""An uploaded row's currency on the line, none for the company's; the problem of one not in the list."""
	currency = _text(values.get("currency"))
	if currency and currency.lower() != (company_currency or "").lower():
		row["currency"] = lists["Currency"].get(currency.lower())
		if not row["currency"]:
			return [_("currency {0} is not in the currency list").format(currency)]
	else:
		row["currency"], row["exchange_rate"] = None, 1
	return []


def _staged(description, staged):
	"""The stage of the line of an imported good's description ({description key: stage}): the same
	description, or one starting the other."""
	key = _key(description)
	if key in staged:
		return staged[key]
	return next((stage for other, stage in staged.items() if len(key) >= 12 and (other.startswith(key) or key.startswith(other))), None)


def _sheet_lines(sheet, rows, milestones, units, tax_defaults):
	"""{lines: [(where, values, whether the sheet gives the VAT)], goods: the imported goods of a tax
	computation, skipped: rows skipped} of one sheet: its lines with the section and stage the sheet gives
	each (see read_cost_lines)."""
	header, columns, money, number_column = _heading_row(rows)
	if header is None:
		return {"lines": [], "goods": [], "skipped": 0}
	titles = [t for t in (_heading_text(_row_text(r)) for r in rows[:header]) if t]
	section = SECTION_NAMES.get(_key(_heading_text(sheet)))
	above = next((SECTION_NAMES[_key(t)] for t in reversed(titles) if _key(t) in SECTION_NAMES), None)
	if above and (not section or {section, above} <= {"Preliminaries", "Administrative"}):
		section = above
	taxes = _tax_lines(sheet, rows, header, columns, money, tax_defaults) if section == "Taxes and Freight" else None
	if taxes:
		return {"lines": taxes[1], "goods": taxes[0], "skipped": 0}
	# a phase's sheet (Phase 1), or one named after a milestone, gives all its lines that stage; on other sheets
	# the headings of the systems do, the first possibly just above the heading row
	fixed = sheet if not section and (_phase(_stage_words(sheet)) or _match_stage(sheet, milestones)) else None
	stage = fixed or next((t for t in titles[-1:] if _key(t) not in SECTION_NAMES and _match_stage(t, milestones)), None)
	# on a sheet of no one section, as a phase's, each system's block finds its own: its equipment comes first,
	# then an INSTALLATION MATERIALS heading over its materials
	mixed, block = section is None, 0
	vat_given = "rate_includes_vat" in columns.values()
	lines, skipped = [], 0
	for number, row in enumerate(rows[header + 1 :], header + 2):
		values = {field: row[c] if c < len(row) else None for c, field in columns.items()}
		# a sheet without a Currency column may keep each line's amount under "Amount (USD)" or "Amount (UGX)"
		priced = {c: code for c, code in money.items() if c < len(row) and _number(row[c])}
		amount = next((_number(row[c]) for c in priced), None)
		if not any(_text(values.get(f)) for f in ("qty", "rate", "contract_percent")):
			text = _heading_text(_row_text(row))
			named = SECTION_NAMES.get(_key(text))
			if amount and LUMP_SUMS.search(text) and "total" not in text.lower():
				# taxes or freight given as an amount alone
				lump = {"section": "Taxes and Freight", "stage": stage or "", "description": _title(text), "qty": 1, "rate": amount}
				lump["currency"] = next(iter(priced.values()))
				lines.append((_("{0} row {1}").format(sheet, number), lump, False))
			elif named:
				if mixed and named == "Installation Materials":
					for _where, earlier, _given in lines[block:]:
						earlier["section"] = earlier["section"] or "Equipment"
				section, stage = named, fixed
			elif text and "total" not in text.lower() and (_match_stage(text, milestones) or _looks_like_heading(text)):
				stage = fixed or text
				if mixed and section in (None, "Equipment", "Installation Materials"):
					section, block = None, len(lines)
			elif text:
				skipped += 1
			continue
		values["section"] = _text(values.get("section")) or section or ""
		values["stage"] = _text(values.get("stage")) or stage or ""
		labour = SECTION_NAMES.get(_key(values["section"])) == "Labour"
		if labour and number_column is not None and number_column < len(row) and not _text(values.get("people")):
			values["people"] = row[number_column]
		if not _fits(values, amount):
			values = _realign(values, row, columns, amount, units)
		if not _text(values.get("currency")) and len(set(priced.values())) == 1:
			values["currency"] = next(iter(priced.values()))
		lines.append((_("{0} row {1}").format(sheet, number), values, vat_given))
	return {"lines": lines, "goods": [], "skipped": skipped}


def _fits(values, amount) -> bool:
	"""Whether a row reads right under its heading row: numbers where the people and qty go, no number where
	the unit goes, and people x qty x rate making the row's own amount where it has one."""
	people, qty, rate, unit = (values.get(f) for f in ("people", "qty", "rate", "uom"))
	if any(_text(v) and _number(v) is None for v in (people, qty)) or (_text(unit) and _number(unit) is not None):
		return False
	if not amount or not _number(rate):
		return True
	made = (_number(people) or 1) * (_number(qty) if _text(qty) else 1) * _number(rate)
	return abs(made - amount) <= max(1.0, abs(amount) / 200)


def _realign(values, row, columns, amount, units):
	"""A row laid out unlike its heading row, as when a phase sheet copies the labour or overhead block of the
	main budget under the materials headings (Details | No | Qty | Unit | Rate under Description | Brand |
	Unit | Qty | Rate), read from what the cells between its description and rate hold: two numbers are the
	people and the qty, one the qty, a unit word the unit and other text the brand. Kept as it was when that
	does not make the row's own amount either."""
	at = {field: c for c, field in columns.items()}
	start, end = at.get("description", at.get("item_code")), at.get("rate")
	if start is None or end is None or end <= start + 1:
		return values
	cells = [row[c] for c in range(start + 1, min(end, len(row))) if _text(row[c])]
	numbers = [_number(v) for v in cells if _number(v) is not None]
	texts = [_text(v) for v in cells if _number(v) is None]
	if len(numbers) > 2:
		return values
	people, qty = ([1.0, 1.0] + numbers)[-2:]
	rate = _number(values.get("rate"))
	if amount and rate and abs(people * qty * rate - amount) > max(1.0, abs(amount) / 200):
		return values
	unit = next((t for t in texts if t.lower().rstrip(".") in units or t.lower().rstrip(".") in UNIT_ALIASES or t.lower().rstrip(".") in UNIT_WORDS), None)
	return {**values, "people": people, "qty": qty, "uom": unit, "brand": next((t for t in texts if t != unit), None)}


def _tax_lines(sheet, rows, header, columns, money, defaults):
	"""A tax computation, as the business's Taxes sheet or the Tax Computation sheet given out here: (its
	imported goods, each the values of a tax computation line, [(where, values, False)]; the freight below
	them as lines of Taxes and Freight). None for a sheet that is not one. A sheet giving the taxes but not
	their rates, as the Taxes sheet, has each good's rates worked out from its own figures, so they stand;
	a good without figures takes the usual rates."""
	heads = {}
	for c, value in enumerate(rows[header]):
		key = _key(_heading_text(value))
		if c not in columns and key in TAX_HEADINGS:
			heads[c] = TAX_HEADINGS[key]
	if len({"insurance", "duty", "levy"} & set(heads.values())) < 2:
		return None
	currency = next(iter(money.values()), "")
	goods, freight = [], []
	for number, row in enumerate(rows[header + 1 :], header + 2):
		values = {field: row[c] if c < len(row) else None for c, field in {**columns, **heads}.items()}
		text = _row_text(row)
		where = _("{0} row {1}").format(sheet, number)
		if "total" in text.lower():
			continue
		if "freight" in text.lower() and not _number(values.get("qty")):
			amount = next((float(v) for v in reversed(row) if isinstance(v, (int, float)) and v), None)
			if amount:
				line = {"section": "Taxes and Freight", "description": re.split(r"[/(]", text)[0].strip() or _("Freight"), "qty": 1, "rate": amount}
				freight.append((where, {**line, "currency": _text(values.get("currency")) or currency}, False))
			continue
		if not _text(values.get("description")):
			continue
		value = _number(values.get("value"))
		if value is None:
			value = (_number(values.get("qty")) or 1) * (_number(values.get("rate")) or 0)
		insurance, duty = _number(values.get("insurance")), _number(values.get("duty"))
		customs = _number(values.get("customs_value"))
		if customs is None:
			customs = value + (insurance or 0)
		bases = {
			"insurance_percent": (insurance, value), "duty_percent": (duty, customs),
			"vat_percent": (_number(values.get("vat")), customs + (duty or 0)), "levy_percent": (_number(values.get("levy")), customs),
		}
		for field, (amount, base) in bases.items():
			if _number(values.get(field)) is None:
				values[field] = flt(amount / base * 100, 2) if amount is not None and base else defaults[field]
		values["currency"] = _text(values.get("currency")) or currency
		goods.append((where, values, False))
	return goods, freight


def _heading_row(rows):
	"""(index, {column: field}, {column: currency}, the column of No or None) of the heading row among a
	sheet's first rows: one naming Description or Item Code, and Qty, Rate or % of Contract Value. The
	currencies are those of amount columns such as "Amount (USD)". (None, None, None, None) for a sheet
	without lines."""
	headings = {_key(f): f for f, _heading in EXCEL_COLUMNS} | {_key(h): f for f, h in EXCEL_COLUMNS} | HEADING_ALIASES
	for index, row in enumerate(rows[:15]):
		columns = {c: headings[_key(v)] for c, v in enumerate(row) if _key(v) in headings}
		found = set(columns.values())
		if found & {"description", "item_code"} and found & {"qty", "rate", "contract_percent"}:
			money, number_column = {}, None
			first = min(c for c, f in columns.items() if f in ("description", "item_code"))
			for c, v in enumerate(row):
				if c in columns:
					continue
				code = re.search(r"\(\s*([A-Za-z]{3}|\$)\s*\)", _text(v))
				if code:
					money[c] = "USD" if code.group(1) == "$" else code.group(1).upper()
				elif _key(v) == "no" and number_column is None and c > first:
					# after the description a No column counts people (Details | No | Qty); before it, it numbers the rows
					number_column = c
			return index, columns, money, number_column
	return None, None, None, None


def _row_text(row) -> str:
	"""The first piece of text on a row: a heading row's heading."""
	return next((_text(v) for v in row if isinstance(v, str) and v.strip()), "")


def _heading_text(value) -> str:
	"""A heading without its numbering and bracketed notes: "A. EQUIPMENT (VAT Exc.)" -> "EQUIPMENT"."""
	text = re.sub(r"\([^)]*\)", " ", NUMBERING.sub("", _text(value)))
	return re.sub(r"\s+", " ", text).strip(" :-/")


def _looks_like_heading(text) -> bool:
	"""Whether a row's only text reads as a heading: a few words in capitals, as budget sheets head a system."""
	return sum(c.isalpha() for c in text) >= 3 and len(text.split()) <= 8 and _capitals(text)


def _capitals(text) -> bool:
	letters = [c for c in text if c.isalpha()]
	return bool(letters) and sum(c.isupper() for c in letters) >= 0.7 * len(letters)


def _stage_words(text) -> tuple:
	"""A stage's name as words, without numbering, bracketed notes and signs: "Water Supply (Tank & Pump)"
	-> ("water", "supply")."""
	return tuple(re.findall(r"[a-z0-9]+", _heading_text(text).lower()))


def _phase(words) -> bool:
	"""Whether a name's words name a phase: Phase 1, Stage 2."""
	return len(words) >= 2 and words[0] in PHASE_WORDS and words[1].isdigit()


def _stage_index(names) -> dict:
	return {"names": {n.lower(): n for n in names}, "words": {_stage_words(n): n for n in names if _stage_words(n)}}


def _match_stage(text, index):
	"""The milestone of an index (_stage_index) that a Stage cell, sheet or heading names: by name; else by its
	words without numbering and brackets; else, for a phase, the one milestone of that phase (Phase 1 -
	Pipe Work for Phase 1); else nearly the same words with the same numbers, as with a slip (FIGHTNG for
	FIGHTING). None for none."""
	text = _text(text)
	if text.lower() in index["names"]:
		return index["names"][text.lower()]
	words = _stage_words(text)
	if not words:
		return None
	if words in index["words"]:
		return index["words"][words]
	if _phase(words):
		same = [n for w, n in index["words"].items() if w[:2] == words[:2]]
		return same[0] if len(same) == 1 else None
	joined = "".join(words)
	digits = re.sub(r"\D", "", joined)
	candidates = {"".join(w): n for w, n in index["words"].items() if re.sub(r"\D", "", "".join(w)) == digits}
	close = difflib.get_close_matches(joined, list(candidates), n=1, cutoff=0.9) if len(joined) >= 6 else []
	return candidates[close[0]] if close else None


def _new_stages(texts) -> dict:
	"""{stage text: name} for the stages of a file ({text: lines}) not in the milestone list: texts nearly the
	same are one stage, under the spelling most lines have."""
	names = {}
	for text in sorted(texts, key=lambda t: -texts[t]):
		names[text] = _match_stage(text, _stage_index(names.values())) or _title(text)
	return names


def _title(text) -> str:
	"""A heading in capitals as a name: WATER SUPPLY & DRAINAGE WORKS -> Water Supply & Drainage Works (kVA kept)."""
	if not _capitals(text):
		return text
	return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize() if m.group(0).isupper() else m.group(0), text)


def _read_sheets(filename, data) -> list:
	"""[(sheet name, rows)] of an .xlsx, .xls or .csv file."""
	extension = (filename or "").rsplit(".", 1)[-1].lower()
	if extension == "csv":
		from frappe.utils.csvutils import read_csv_content

		return [("CSV", read_csv_content(data))]
	if extension == "xls":
		import xlrd

		book = xlrd.open_workbook(file_contents=data)
		return [(s.name, [s.row_values(i) for i in range(s.nrows)]) for s in book.sheets()]
	from openpyxl import load_workbook

	book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
	return [(ws.title, [list(row) for row in ws.iter_rows(values_only=True)]) for ws in book.worksheets]


def _named(doctype, values, title_field) -> dict:
	"""{lowercased name or title: name} of the records of doctype named or titled as in values."""
	found = {}
	if not values:
		return found
	for field in ("name", title_field):
		for record in frappe.get_all(doctype, filters={field: ("in", list(values))}, fields=["name", title_field]):
			found.setdefault((record.get(field) or "").lower(), record.name)
	return found


def _key(value) -> str:
	return re.sub(r"[^a-z]", "", str(value or "").lower())


def _text(value) -> str:
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	return str(value).strip() if value is not None else ""


def _number(value):
	if isinstance(value, (int, float)):
		return float(value)
	try:
		return float(_text(value).replace(",", "").replace("%", ""))
	except ValueError:
		return None


def _yes(value) -> str:
	return "Yes" if value else "No"
