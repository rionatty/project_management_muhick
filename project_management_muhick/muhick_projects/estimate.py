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

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

from project_management_muhick.muhick_projects.utils import get_phases
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
