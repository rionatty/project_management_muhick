# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Supplier Quotation Comparison: the quotations of one request for quotation side by side, approved or not, because the
supplier is chosen from this before its quotation goes for approval. Each line requested is a row with each supplier's
price and amount in the company's currency, so that any two can be weighed, beside what the project's budget allows, and the
lowest marked; what a supplier quoted beyond the request follows, then each quotation's totals and terms.

ERPNext's report of this name lists the quotations of a period one after the other. install.py points the report at this
module, so the sidebar and the request for quotation's View menu open this one."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, formatdate

from project_management_muhick.muhick_projects import budget_engine

SAME = 0.005


def execute(filters=None):
	filters = frappe._dict(filters or {})
	request = filters.request_for_quotation
	if not request:
		return [], []
	company = frappe.db.get_value("Request for Quotation", request, "company")
	home = frappe.get_cached_value("Company", company, "default_currency")
	quotations, expired = _quotations(request, filters.include_expired)
	requested = frappe.get_all(
		"Request for Quotation Item",
		filters={"parent": request},
		fields=["name", "item_code", "item_name", "qty", "uom", "stock_qty", "conversion_factor", "project_name"],
		order_by="idx asc",
	)
	cells, extras = _quoted(request, requested, quotations)
	budgets = _budgets(requested)
	rows = [_row(line, line.name, quotations, cells, home, budgets) for line in requested]
	rows += [_row(line, key, quotations, cells, home, budgets) for key, line in extras.items()]
	rows += _totals(quotations, requested, cells, home)
	message = []
	if not quotations:
		message.append(_("No quotations have been recorded against {0} yet.").format(request))
	if expired:
		message.append(_("{0} expired quotations are left out.").format(expired))
	return _columns(quotations, requested, cells, budgets), rows, " ".join(message) or None


def _budgets(requested) -> dict:
	"""{(project, item): (quantity, cost of one stock unit)} on the approved budgets of the lines requested."""
	budgets = {}
	for project in {line.project_name for line in requested if line.project_name}:
		items = {line.item_code for line in requested if line.project_name == project}
		costs = budget_engine.budget_costs(project, items)
		for item, qty in budget_engine.budgeted_quantities(project, items)[0].items():
			budgets[(project, item)] = (flt(qty), flt(costs.get(item)))
	return budgets


def _quotations(request, include_expired) -> tuple:
	"""Those holding a line of the request, oldest first, and how many were left out as expired."""
	names = frappe.get_all("Supplier Quotation Item", filters={"request_for_quotation": request, "docstatus": ("<", 2)}, pluck="parent")
	found = frappe.get_all(
		"Supplier Quotation",
		filters={"name": ("in", list(set(names))), "docstatus": ("<", 2)},
		fields=[
			"name", "supplier", "supplier_name", "status", "workflow_state", "currency", "conversion_rate", "valid_till", "tc_name", "incoterm",
			"grand_total", "base_grand_total", "base_total_taxes_and_charges",
		],
		order_by="transaction_date asc, name asc",
	) if names else []
	kept = [quotation for quotation in found if include_expired or quotation.status != "Expired"]
	return kept, len(found) - len(kept)


def _quoted(request, requested, quotations) -> tuple:
	"""{(quotation, row of the report): what it quoted there}, and the rows for what was quoted beyond the request. A line
	belonging to another request is not this comparison's."""
	cells = defaultdict(lambda: frappe._dict(amount=0.0, stock_qty=0.0, qty=0.0, lead_time=0, brand=None))
	extras = {}
	if not quotations:
		return cells, extras
	names = {line.name for line in requested}
	of_item = {}
	for line in requested:
		of_item.setdefault(line.item_code, line.name)
	for line in frappe.get_all(
		"Supplier Quotation Item",
		filters={"parent": ("in", [quotation.name for quotation in quotations])},
		fields=[
			"parent", "item_code", "item_name", "uom", "qty", "stock_qty", "base_net_amount", "lead_time_days", "brand", "request_for_quotation",
			"request_for_quotation_item",
		],
		order_by="idx asc",
	):
		if line.request_for_quotation and line.request_for_quotation != request:
			continue
		place = line.request_for_quotation_item if line.request_for_quotation_item in names else of_item.get(line.item_code)
		if not place:
			place = ("beyond", line.item_code)
			extras.setdefault(place, frappe._dict(item_code=line.item_code, item_name=line.item_name, uom=line.uom))
		cell = cells[(line.parent, place)]
		cell.amount += flt(line.base_net_amount)
		cell.stock_qty += flt(line.stock_qty)
		cell.qty += flt(line.qty)
		cell.lead_time = max(cell.lead_time, flt(line.lead_time_days))
		cell.brand = cell.brand or line.brand
	return cells, extras


def _rate(cell, line):
	"""What a supplier asks for one of the unit requested, however it quoted, so that any two can be weighed."""
	if not cell.amount:
		return None
	if line.get("name") and cell.stock_qty:
		return cell.amount / cell.stock_qty * (flt(line.conversion_factor) or 1)
	return cell.amount / cell.qty if cell.qty else None


def _lowest(values) -> list:
	"""The indexes of the lowest of {index: value}, ties included."""
	values = {index: value for index, value in values.items() if value}
	return [index for index, value in values.items() if value - min(values.values()) < SAME] if values else []


def _row(line, key, quotations, cells, home, budgets) -> dict:
	row = {
		"item_code": line.item_code, "item_name": line.item_name, "qty": line.get("qty"), "uom": line.uom, "currency": home,
	}
	factor = flt(line.get("conversion_factor")) or 1
	budget_qty, budget_cost = budgets.get((line.get("project_name"), line.item_code), (None, None))
	if budget_qty is not None:
		row.update(budget_qty=budget_qty / factor, budget_rate=budget_cost * factor)
	rates = {}
	for index, quotation in enumerate(quotations):
		cell = cells.get((quotation.name, key))
		if not cell:
			continue
		rates[index] = _rate(cell, line)
		row.update(
			{
				f"rate_{index}": rates[index],
				f"amount_{index}": cell.amount or None,
				f"qty_{index}": cell.qty or None,
				f"brand_{index}": cell.brand,
			}
		)
	lowest = _lowest(rates)
	row["lowest"] = ", ".join(quotations[index].supplier_name for index in lowest)
	row["lowest_cells"] = [f"rate_{index}" for index in lowest]
	row["over_cells"] = [f"rate_{index}" for index, rate in rates.items() if rate and budget_cost and rate - budget_cost * factor > SAME]
	return row


def _totals(quotations, requested, cells, home) -> list:
	"""Below the lines: what each comes to, the lowest among those that priced every line, and each quotation's terms."""
	if not quotations:
		return []
	spent = {index: sum(cell.amount for (name, _place), cell in cells.items() if name == quotation.name) for index, quotation in enumerate(quotations)}
	priced = {index: sum(1 for line in requested if cells.get((quotation.name, line.name)) and _rate(cells[(quotation.name, line.name)], line)) for index, quotation in enumerate(quotations)}
	complete = [index for index, count in priced.items() if count == len(requested)]
	in_the_running = set(complete or priced)

	def money(label, values, compare=False):
		row = {"item_name": label, "bold": 1, "currency": home}
		row.update({f"amount_{index}": value for index, value in values.items()})
		if compare:
			lowest = _lowest({index: value for index, value in values.items() if index in in_the_running})
			row["lowest"] = ", ".join(quotations[index].supplier_name for index in lowest)
			row["lowest_cells"] = [f"amount_{index}" for index in lowest]
		return row

	def fact(label, values, kind=1):
		return {"item_name": label, "fact": kind, **{f"amount_{index}": value for index, value in enumerate(values)}}

	rows = [money(_("Total"), spent, compare=True)]
	if any(flt(quotation.base_total_taxes_and_charges) for quotation in quotations):
		rows.append(money(_("Taxes and Charges"), {index: flt(quotation.base_total_taxes_and_charges) for index, quotation in enumerate(quotations)}))
		rows.append(money(_("Grand Total"), {index: flt(quotation.base_grand_total) for index, quotation in enumerate(quotations)}, compare=True))
	rows.append(fact(_("Items Quoted"), [_("{0} of {1}").format(priced[index], len(requested)) for index in range(len(quotations))]))
	if any(quotation.currency != home for quotation in quotations):
		rows.append(fact(_("Quoted In"), [f"{quotation.currency} {_('at')} {flt(quotation.conversion_rate):,g}" if quotation.currency != home else quotation.currency for quotation in quotations]))
		rows.append(fact(_("As Quoted"), [fmt_money(quotation.grand_total, currency=quotation.currency) for quotation in quotations]))
	longest = [max((cell.lead_time for (name, _place), cell in cells.items() if name == quotation.name), default=0) for quotation in quotations]
	for label, values in (
		(_("Lead Time (Days)"), [f"{days:g}" if days else None for days in longest]),
		(_("Valid Till"), [formatdate(quotation.valid_till) if quotation.valid_till else None for quotation in quotations]),
		(_("Terms"), [quotation.tc_name for quotation in quotations]),
		(_("Incoterm"), [quotation.incoterm for quotation in quotations]),
	):
		if any(values):
			rows.append(fact(label, values))
	rows.append(fact(_("Quotation"), [quotation.name for quotation in quotations], "link"))
	rows.append(fact(_("Status"), [_(quotation.workflow_state or quotation.status) for quotation in quotations]))
	return rows


def _columns(quotations, requested, cells, budgets) -> list:
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 240},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 80},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
	]
	if budgets:
		columns += [
			{"fieldname": "budget_qty", "label": _("Budget Qty"), "fieldtype": "Float", "width": 90},
			{"fieldname": "budget_rate", "label": _("Budget Rate"), "fieldtype": "Currency", "options": "currency", "width": 120},
		]
	wanted = {line.name: flt(line.stock_qty) for line in requested}
	names = [quotation.supplier_name for quotation in quotations]
	for index, quotation in enumerate(quotations):
		supplier = quotation.supplier_name
		if names.count(supplier) > 1:
			supplier = f"{supplier} ({quotation.name})"
		width = max(130, min(200, 8 * len(supplier) + 50))
		mine = {place: cell for (name, place), cell in cells.items() if name == quotation.name}
		columns += [
			{"fieldname": f"rate_{index}", "label": f"{supplier}: {_('Rate')}", "fieldtype": "Currency", "options": "currency", "width": width},
			{"fieldname": f"amount_{index}", "label": f"{supplier}: {_('Amount')}", "fieldtype": "Currency", "options": "currency", "width": width},
		]
		# only where it says something
		if any(place in wanted and abs(cell.stock_qty - wanted[place]) > SAME for place, cell in mine.items()):
			columns.append({"fieldname": f"qty_{index}", "label": f"{supplier}: {_('Qty Quoted')}", "fieldtype": "Float", "width": 110})
		if any(cell.brand for cell in mine.values()):
			columns.append({"fieldname": f"brand_{index}", "label": f"{supplier}: {_('Brand')}", "fieldtype": "Data", "width": 110})
	columns.append({"fieldname": "lowest", "label": _("Lowest"), "fieldtype": "Data", "width": 180})
	return columns
