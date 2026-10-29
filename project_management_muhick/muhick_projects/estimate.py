# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid's cost estimate, and the project budget it becomes.

The estimate is built on the opportunity with the very lines of a project budget (Project Budget
Line): each a stage from the shared milestone list, an item or a description, its supplier and
brand, its cost code, and an amount in the company's currency without VAT, which is people x qty x
rate at the line's exchange rate (a rate quoted with VAT taken without it), or a share of the
contract value. When the project is handed over, the estimate becomes the project's draft budget,
which the Project Manager adjusts before sending it for approval. A budget line takes the project's
milestone (phase) of its stage once the activity plan has created it."""

import base64
import io
import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

from project_management_muhick.muhick_projects.utils import ensure_milestone, get_phases
from project_management_muhick.muhick_sales.bids import boq_factor, boq_quotes, last_purchase_rate, latest_by_supplier, lowest, project_bid
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import get_settings, setting

# what a line carries from the estimate to the budget
LINE_FIELDS = (
	"stage", "item_code", "description", "uom", "brand", "supplier", "people", "qty", "rate", "currency", "exchange_rate",
	"rate_includes_vat", "contract_percent", "cost_code", "procurement_type", "remarks",
)
SECTIONS = ("Materials", "Works", "Administrative")
# the settings a cost estimate works with, and their values until Muhick sets its own
DEFAULTS = {"vat_percent": 18, "import_insurance_percent": 1.5, "import_duty_percent": 10, "import_levy_percent": 1.5}


def set_amounts(doc, lines, contract_value) -> float:
	"""Each line's amount in the company's currency without VAT; returns their total. A line priced as
	a share of the contract value reads as one lot at that amount."""
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") if doc.get("company") else None
	vat = flt(setting("vat_percent", DEFAULTS["vat_percent"]))
	label = _(doc.meta.get_label(lines[0].parentfield)) if lines else ""
	total = 0.0
	for line in lines:
		if line.currency and line.currency != company_currency:
			if not flt(line.exchange_rate):
				frappe.throw(_("{0} row {1}: give the exchange rate of {2}.").format(label, line.idx, line.currency))
		else:
			line.currency, line.exchange_rate = None, 1
		line.people = line.people or 1
		line.amount = calc.line_amount(
			line.qty, line.rate, line.people, line.exchange_rate, line.rate_includes_vat, vat, line.contract_percent, contract_value
		)
		if flt(line.contract_percent):
			line.update({"qty": 1, "rate": line.amount, "people": 1, "currency": None, "exchange_rate": 1, "rate_includes_vat": 0})
		total += flt(line.amount)
	return total


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
	supplier quotation for the bid, or else at its last purchase price, with its brand and cost code."""
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
		row = {
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


@frappe.whitelist()
def get_import_costs(
	goods_value: float, freight: float = 0, insurance_percent: float = 0, duty_percent: float = 0,
	levy_percent: float = 0, stage: str | None = None, supplier: str | None = None,
) -> list:
	"""Estimate lines for importing goods worth goods_value in the company's currency: insurance,
	freight, and import duty and infrastructure levy on the customs value (VAT is claimed back), under
	the cost code for import costs."""
	costs = calc.import_costs(goods_value, freight, insurance_percent, duty_percent, levy_percent)
	whose = _(" on goods from {0}").format(supplier) if supplier else ""
	rows = []
	for key, label, percent in (
		("insurance", _("Insurance"), insurance_percent),
		("freight", _("Freight"), None),
		("duty", _("Import duty"), duty_percent),
		("levy", _("Infrastructure levy"), levy_percent),
	):
		if flt(costs[key]):
			rate = f" {flt(percent):g}%" if percent is not None else ""
			rows.append(
				{
					"stage": stage, "description": f"{label}{rate}{whose}", "qty": 1, "rate": costs[key], "people": 1,
					"exchange_rate": 1, "cost_code": get_settings().get("import_cost_code"), "procurement_type": "Not Applicable",
				}
			)
	return rows


# ------------------------------------------------------------------ from the estimate to the budget
def estimate_rows(opportunity) -> list:
	"""The bid's cost estimate, line by line, ready to become budget lines."""
	lines = frappe.get_all(
		"Project Budget Line",
		filters={"parent": opportunity, "parenttype": "Opportunity", "parentfield": "muhick_estimate"},
		fields=list(LINE_FIELDS),
		order_by="idx asc",
	)
	return [{f: line.get(f) for f in LINE_FIELDS} for line in lines]


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
	"""For the Budget Summary print: the budget's cost codes, section by section, against its stages in
	the order of the project's milestones (each with its months), then the contract value and margin."""
	lines = doc.get("lines") or []
	milestones = {}
	for phase in get_phases(doc.project, ("name", "type", "subject", "exp_start_date", "exp_end_date")) if doc.get("project") else []:
		milestones.setdefault(phase.type or phase.subject, phase)
	stages = [s for s in milestones if any((line.stage or "") == s for line in lines)]
	stages += [s for s in dict.fromkeys(line.stage or "" for line in lines) if s not in stages and s]
	if any(not line.stage for line in lines):
		stages.append("")
	cells, sections, names = defaultdict(float), defaultdict(set), {}
	for line in lines:
		cells[(line.cost_code, line.stage or "")] += flt(line.amount)
		sections[line.budget_section or frappe.get_cached_value("Cost Code", line.cost_code, "budget_section") or ""].add(line.cost_code)
	for code in {line.cost_code for line in lines if line.cost_code}:
		names[code] = frappe.get_cached_value("Cost Code", code, "cost_code_name")

	def amounts(codes):
		values = [sum(cells[(code, stage)] for code in codes) for stage in stages]
		return values, sum(values)

	blocks = []
	for section in [*SECTIONS, *sorted(s for s in sections if s not in SECTIONS)]:
		codes = sorted(sections.get(section) or [])
		if not codes:
			continue
		rows = []
		for code in codes:
			values, total = amounts([code])
			rows.append({"cost_code": code, "name": names.get(code) or "", "amounts": values, "total": total})
		values, total = amounts(codes)
		blocks.append({"section": section, "rows": rows, "amounts": values, "total": total})
	values, total = amounts([code for codes in sections.values() for code in codes])
	contract = flt(doc.get("contract_value"))
	current = flt(doc.get("total_current_budget")) or total
	return {
		"stages": [{"name": s, "period": _period(milestones.get(s))} for s in stages],
		"sections": blocks,
		"amounts": values,
		"total": total,
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
# a budget prepared in Excel comes in through the Excel file the system gives out: one row per line
TABLES = {"Opportunity": "muhick_estimate", "Project Budget": "lines"}
EXCEL_COLUMNS = (
	# "Item Code", not "Item": budget sheets often number their rows in an Item column
	("stage", "Stage"), ("item_code", "Item Code"), ("description", "Description"), ("uom", "UOM"), ("brand", "Brand"),
	("supplier", "Supplier"), ("people", "People"), ("qty", "Qty"), ("rate", "Rate"), ("currency", "Currency"),
	("exchange_rate", "Exchange Rate"), ("rate_includes_vat", "Rate Includes VAT"), ("contract_percent", "% of Contract Value"),
	("cost_code", "Cost Code"), ("procurement_type", "Procurement Type"), ("remarks", "Remarks"),
)
# other headings budget sheets use for the same columns
HEADING_ALIASES = {
	"milestone": "stage", "phase": "stage", "details": "description", "unit": "uom",
	"quantity": "qty", "vatinclusive": "rate_includes_vat", "includesvat": "rate_includes_vat", "comments": "remarks",
	"contractvalue": "contract_percent",
}
# units as budget sheets write them, for the units of the unit list
UNIT_ALIASES = {
	"pcs": "Nos", "pce": "Nos", "no": "Nos", "number": "Nos", "piece": "Nos", "pieces": "Nos",
	"m": "Meter", "meters": "Meter", "metres": "Meter", "ltrs": "Litre", "litres": "Litre", "liters": "Litre",
}
PROCUREMENT_TYPES = ("Local", "International", "From Stock", "Not Applicable")
YES = ("yes", "y", "true", "1", "x")


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
	"""An Excel file of an estimate's or a budget's lines, to prepare or change in Excel and upload again:
	each line's amount worked out as on screen, lists to pick the stage, cost code, currency, procurement
	type and VAT from, and those lists on a sheet of their own."""
	from openpyxl import Workbook
	from openpyxl.styles import Font
	from openpyxl.worksheet.datavalidation import DataValidation

	doc = _cost_doc(doctype, name, "read")
	lines = doc.get(TABLES[doctype]) if doc else []
	book = Workbook()
	sheet = book.active
	sheet.title = "Cost Lines"
	sheet.append([heading for _field, heading in EXCEL_COLUMNS] + ["Amount"])
	for line in lines:
		sheet.append([(_yes(line.get(f)) if f == "rate_includes_vat" else line.get(f)) for f, _heading in EXCEL_COLUMNS])
	vat = flt(setting("vat_percent", DEFAULTS["vat_percent"]))
	last = len(lines) + 300
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

	lists = book.create_sheet("Lists")
	values = {
		"A": ["Stage", *frappe.get_all("Task Type", pluck="name", order_by="name asc")],
		"B": ["Cost Code", *frappe.get_all("Cost Code", filters={"disabled": 0}, pluck="name", order_by="name asc")],
		"E": ["Currency", *frappe.get_all("Currency", filters={"enabled": 1}, pluck="name", order_by="name asc")],
		"F": ["Procurement Type", *PROCUREMENT_TYPES],
		"G": ["Rate Includes VAT", "Yes", "No"],
	}
	codes = frappe.get_all("Cost Code", filters={"disabled": 0}, fields=["name", "cost_code_name", "budget_section"], order_by="name asc")
	values["C"] = ["Description", *[c.cost_code_name for c in codes]]
	values["D"] = ["Section", *[c.budget_section for c in codes]]
	for column, items in values.items():
		for r, value in enumerate(items, 1):
			lists[f"{column}{r}"] = value
		lists[f"{column}1"].font = Font(bold=True)
		lists.column_dimensions[column].width = 40 if column == "C" else 20
	for target, column in (("A", "A"), ("N", "B"), ("J", "E"), ("O", "F"), ("L", "G")):
		rule = DataValidation(type="list", formula1=f"Lists!${column}$2:${column}${max(len(values[column]), 2)}", allow_blank=True)
		rule.add(f"{target}2:{target}{last}")
		sheet.add_data_validation(rule)

	out = io.BytesIO()
	book.save(out)
	frappe.response["filename"] = f"{name or _(doctype)} - Cost Lines.xlsx"
	frappe.response["filecontent"] = out.getvalue()
	frappe.response["type"] = "binary"


@frappe.whitelist()
def read_cost_lines(doctype: str, filename: str, content: str, name: str | None = None, company: str | None = None) -> dict:
	"""The cost lines of an uploaded Excel (.xlsx or .xls) or CSV file, checked row by row: {rows, errors,
	notes}. Every sheet with a heading row (Description or Item, and Qty, Rate or % of Contract Value) is
	read; rows with neither a qty, a rate nor a percentage are headings or totals and are skipped. With
	any error nothing is taken, so the file can be corrected and uploaded again."""
	doc = _cost_doc(doctype, name, "write")
	raw, skipped, without_codes = [], 0, set()
	for sheet, rows in _read_sheets(filename, base64.b64decode(content.split(",", 1)[-1])):
		header, columns, money = _heading_row(rows)
		if header is None:
			continue
		if "cost_code" not in columns.values():
			without_codes.add(sheet)
		for number, row in enumerate(rows[header + 1 :], header + 2):
			values = {field: row[c] if c < len(row) else None for c, field in columns.items()}
			if not any(_text(values.get(f)) for f in ("qty", "rate", "contract_percent")):
				skipped += any(_text(v) for v in values.values())
				continue
			# a sheet without a Currency column may keep each line's amount under "Amount (USD)" or "Amount (UGX)"
			priced_in = {code for c, code in money.items() if c < len(row) and _number(row[c])}
			if not _text(values.get("currency")) and len(priced_in) == 1:
				values["currency"] = priced_in.pop()
			raw.append((_("{0} row {1}").format(sheet, number), values, sheet))
	if not raw:
		return {
			"rows": [], "notes": [],
			"errors": [_("No cost lines found. The first row needs headings such as Description, Qty, Rate and Cost Code, as in the Excel file downloaded from here.")],
		}

	wanted = lambda field: {_text(v.get(field)) for _w, v, _s in raw if _text(v.get(field))}  # noqa: E731
	items, suppliers = _named("Item", wanted("item_code"), "item_name"), _named("Supplier", wanted("supplier"), "supplier_name")
	codes = {}
	for code in frappe.get_all("Cost Code", filters={"disabled": 0}, fields=["name", "cost_code_name"]):
		codes[code.name.lower()] = code.name
		codes.setdefault((code.cost_code_name or "").lower(), code.name)
	lists = {
		doctype_: {n.lower(): n for n in frappe.get_all(doctype_, pluck="name")}
		for doctype_ in ("Task Type", "Currency", "UOM", "Brand")
	}
	company = doc.company if doc else company
	company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	may_add_stages = frappe.has_permission("Task Type", "create")
	errors, rows, new_stages, unknown, uncoded = [], [], set(), defaultdict(set), defaultdict(int)
	for where, values, sheet in raw:
		row, problems, extra = {"people": 1}, [], []
		item = _text(values.get("item_code"))
		if item and not items.get(item.lower()):
			problems.append(_("item {0} is not in the item list").format(item))
		row["item_code"] = items.get(item.lower()) if item else None
		stage = _text(values.get("stage"))
		if stage:
			row["stage"] = lists["Task Type"].get(stage.lower()) or stage
			listed = stage.lower() in lists["Task Type"]
			if not listed and may_add_stages:
				new_stages.add(stage)
			elif not listed:
				problems.append(_("stage {0} is not in the milestone list").format(stage))
		row["description"] = _text(values.get("description")) or (
			frappe.get_cached_value("Item", row["item_code"], "item_name") if row["item_code"] else ""
		)
		if not row["description"]:
			problems.append(_("give an item or a description"))
		unit = _text(values.get("uom"))
		if unit:
			row["uom"] = lists["UOM"].get(unit.lower()) or lists["UOM"].get(UNIT_ALIASES.get(unit.lower().rstrip("."), "").lower())
			if not row["uom"]:
				unknown[_("Units not in the unit list, left blank")].add(unit)
		for field, records, label in (("brand", lists["Brand"], _("Brand")), ("supplier", suppliers, _("Supplier"))):
			value = _text(values.get(field))
			row[field] = records.get(value.lower()) if value else None
			if value and not row[field]:
				unknown[_("Not in the {0} list, kept in the remarks").format(label.lower())].add(value)
				extra.append(f"{label}: {value}")
		for field in ("people", "qty", "rate", "exchange_rate", "contract_percent"):
			value = values.get(field)
			if _text(value):
				number = _number(value)
				if number is None:
					problems.append(_("{0} is not a number").format(value))
				else:
					row[field] = number
		row["people"] = int(row["people"]) or 1
		row["qty"] = row.get("qty", 1) if not row.get("contract_percent") else 1
		currency = _text(values.get("currency"))
		if currency and currency.lower() != (company_currency or "").lower():
			row["currency"] = lists["Currency"].get(currency.lower())
			if not row["currency"]:
				problems.append(_("currency {0} is not in the currency list").format(currency))
		else:
			row["currency"], row["exchange_rate"] = None, 1
		row["rate_includes_vat"] = 1 if _text(values.get("rate_includes_vat")).lower() in YES else 0
		code = _text(values.get("cost_code"))
		row["cost_code"] = codes.get(code.lower()) if code else (
			frappe.get_cached_value("Item", row["item_code"], "muhick_cost_code") if row["item_code"] else None
		)
		if not row["cost_code"] and not code and sheet in without_codes:
			uncoded[sheet] += 1  # one message for the sheet, below
		elif not row["cost_code"]:
			problems.append(_("cost code {0} is not in the cost code list").format(code) if code else _("give a cost code"))
		kind = _text(values.get("procurement_type"))
		row["procurement_type"] = next((k for k in PROCUREMENT_TYPES if k.lower() == kind.lower()), None) if kind else None
		if kind and not row["procurement_type"]:
			problems.append(_("procurement type {0} is not one of {1}").format(kind, ", ".join(PROCUREMENT_TYPES)))
		row["remarks"] = "; ".join(filter(None, [_text(values.get("remarks")), *extra])) or None
		if problems:
			errors.append(f"{where}: {'; '.join(problems)}")
		rows.append(row)

	# a row in a currency without a rate takes the rate its currency has elsewhere in the file, or else on
	# the lines already here
	given, used, missing = {}, {}, set()
	for row in rows:
		if row.get("currency") and flt(row.get("exchange_rate")):
			given.setdefault(row["currency"], row["exchange_rate"])
	for line in doc.get(TABLES[doctype]) if doc else []:
		if line.currency and flt(line.exchange_rate):
			used.setdefault(line.currency, line.exchange_rate)
	for row in rows:
		if not row.get("currency"):
			row["exchange_rate"] = 1
		elif not flt(row.get("exchange_rate")):
			row["exchange_rate"] = given.get(row["currency"]) or used.get(row["currency"])
			if not row["exchange_rate"]:
				missing.add(row["currency"])
	errors += [_("Give the exchange rate of {0} on at least one of its rows.").format(c) for c in sorted(missing)]
	errors += [
		_("{0}: {1} row(s) have no cost code and the sheet has no Cost Code column. Add one, as in the Excel file downloaded from here.").format(sheet, count)
		for sheet, count in uncoded.items()
	]
	if errors:
		more = [_("... and {0} more.").format(len(errors) - 40)] if len(errors) > 40 else []
		return {"rows": [], "errors": errors[:40] + more, "notes": []}

	for stage in new_stages:
		ensure_milestone(stage)
	notes = [f"{label}: {', '.join(sorted(values))}" for label, values in unknown.items()]
	if new_stages:
		notes.append(_("Stages added to the milestone list: {0}").format(", ".join(sorted(new_stages))))
	if skipped:
		notes.append(_("{0} row(s) without a qty, rate or percentage were skipped as headings or totals.").format(skipped))
	return {"rows": [{f: row.get(f) for f in LINE_FIELDS} for row in rows], "errors": [], "notes": notes}


def _heading_row(rows):
	"""(index, {column: field}, {column: currency}) of the heading row among a sheet's first rows: one
	naming Description or Item Code, and Qty, Rate or % of Contract Value. The currencies are those of
	amount columns such as "Amount (USD)". (None, None, None) for a sheet without lines."""
	headings = {_key(f): f for f, _heading in EXCEL_COLUMNS} | {_key(h): f for f, h in EXCEL_COLUMNS} | HEADING_ALIASES
	for index, row in enumerate(rows[:15]):
		columns = {c: headings[_key(v)] for c, v in enumerate(row) if _key(v) in headings}
		found = set(columns.values())
		if found & {"description", "item_code"} and found & {"qty", "rate", "contract_percent"}:
			money = {}
			for c, v in enumerate(row):
				code = re.search(r"\(\s*([A-Za-z]{3}|\$)\s*\)", _text(v)) if c not in columns else None
				if code:
					money[c] = "USD" if code.group(1) == "$" else code.group(1).upper()
			return index, columns, money
	return None, None, None


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
