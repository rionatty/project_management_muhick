# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Pure calculations used across the app.

Nothing in this module imports frappe, so the rules can be unit tested without a site.
"""

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

FULL_ROUTE = "Full Route"
SECOND_APPROVER = "Up to Second Approver"
FIRST_APPROVER = "First Approver Only"


def _f(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _d(value) -> date | None:
	if not value:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


# ------------------------------------------------------------------ budget
def available_budget(current_budget, committed) -> float:
	"""Budget still free to commit.

	A commitment (approved purchase order, subcontract, requisition, labour sheet) takes
	its full value out of the budget at once, whether or not it has been paid:
	budget 300m, committed 270m, paid 80m -> available 30m.
	"""
	return _f(current_budget) - _f(committed)


def forecast_final_cost(current_budget, committed, estimate_to_complete=None) -> float:
	"""Committed cost plus what is still expected to be committed.

	Without a manual estimate the remaining budget is assumed to be spent, so the forecast
	is never below what is already committed.
	"""
	if estimate_to_complete is None:
		estimate_to_complete = max(_f(current_budget) - _f(committed), 0)
	return _f(committed) + _f(estimate_to_complete)


def budget_status(amount, available, budgeted=True) -> str:
	if not budgeted:
		return "Not Budgeted"
	return "Within Budget" if _f(amount) <= _f(available) + 0.005 else "Exceeds Budget"


def budget_line_quantity(qty, people=1, contract_percent=0) -> float:
	"""The quantity of its item a budget line allows: its quantity for each of its people. A line priced
	as a share of the contract value is a sum of money, not a quantity."""
	if _f(contract_percent):
		return 0.0
	return _f(qty) * (_f(people) or 1)


def quantity_excess(budgeted, to_date, adding) -> dict:
	"""{item: total} for the budgeted items a document takes over their budgeted quantity: what is already
	asked for or bought, plus what it adds. An item it adds nothing to, or not budgeted by item, is left out."""
	totals = {item: _f(to_date.get(item)) + _f(qty) for item, qty in adding.items() if _f(qty) > 0 and item in budgeted}
	return {item: total for item, total in totals.items() if total > _f(budgeted[item]) + 1e-9}


def beyond_requests(rows, open_on_requests) -> dict:
	"""{item: quantity} on (item, quantity, request row) rows that their approved requests do not cover.
	open_on_requests: {request row: quantity not yet ordered from it}. A request was checked against the
	budget when it was approved, so only what goes beyond it is new."""
	left = dict(open_on_requests)
	beyond = {}
	for item, qty, source in rows:
		covered = min(_f(qty), left.get(source, 0.0))
		if source in left:
			left[source] -= covered
		beyond[item] = beyond.get(item, 0.0) + _f(qty) - covered
	return {item: qty for item, qty in beyond.items() if qty > 1e-9}


# ------------------------------------------------------------------ cost estimates and budget lines
def line_amount(qty, rate, people=1, exchange_rate=1, includes_vat=False, vat_percent=0, contract_percent=0, contract_value=0) -> float:
	"""A cost estimate or budget line in the company's currency, without VAT.

	People x qty x rate at the line's exchange rate: 4 plumbers for 3 months at 1.5m -> 18m. A rate
	quoted with VAT is taken without it: 118 at 18% -> 100. A line priced as a share of the contract
	value is that share alone: 1% of 2,000m -> 20m. People or an exchange rate left at zero count as one.
	"""
	if _f(contract_percent):
		return _f(contract_value) * _f(contract_percent) / 100
	amount = _f(qty) * _f(rate) * (_f(people) or 1) * (_f(exchange_rate) or 1)
	return amount / (1 + _f(vat_percent) / 100) if includes_vat else amount


def import_taxes(value, insurance_percent=0, duty_percent=0, vat_percent=0, levy_percent=0) -> dict:
	"""The taxes on imported goods worth value, as the business's tax computation works them out.

	The insurance is a share of the value, and the customs value (C.I) is the value with the insurance;
	import duty (ID) and the infrastructure levy (IL) are shares of the customs value, and VAT a share
	of the customs value with the duty: 6,720 at 1.5% insurance, 10% duty, 18% VAT and 1.5% levy ->
	insurance 100.80, customs value 6,820.80, duty 682.08, VAT 1,350.52, levy 102.31, total tax
	2,134.91. What the goods cost the budget besides their price is the insurance, the duty and the
	levy, as the VAT is claimed back.
	"""
	value = _f(value)
	insurance = value * _f(insurance_percent) / 100
	customs_value = value + insurance
	duty = customs_value * _f(duty_percent) / 100
	vat = (customs_value + duty) * _f(vat_percent) / 100
	levy = customs_value * _f(levy_percent) / 100
	return {
		"insurance": insurance, "customs_value": customs_value, "duty": duty, "vat": vat, "levy": levy,
		"total_tax": duty + vat + levy, "cost": insurance + duty + levy,
	}


def price_for_margin(cost, margin_percent, contract_share=0) -> float | None:
	"""The price that leaves a margin on a cost, the margin being a share of the price: cost 930 at 7% ->
	1,000. A cost priced as a share of the contract value rises with the price, so it comes off too: cost
	920 with a 1% share at 7% -> 1,000. None when the margin and the shares leave nothing for the cost.
	"""
	left = round(100 - _f(margin_percent) - _f(contract_share), 6)
	return _f(cost) * 100 / left if left > 0 else None


def boq_line_costs(boq, costs) -> list:
	"""What each BOQ line costs of its own, 0 for a line with none.

	boq is [(item, stage, qty, amount it has now)] and costs [(item, stage, cost)]. A line's own cost is its
	item's in its stage, else its item's left over from stages no line has, shared by qty among the lines
	it goes to.
	"""
	exact, loose = {}, {}
	for item, stage, cost in costs:
		exact[(item, stage)] = exact.get((item, stage), 0.0) + _f(cost)
	on_a_line = {(line[0], line[1]) for line in boq}
	for (item, stage), cost in exact.items():
		if (item, stage) not in on_a_line:
			loose[item] = loose.get(item, 0.0) + cost
	exact_qty, loose_qty = {}, {}
	for item, stage, qty, _amount in boq:
		if exact.get((item, stage)):
			exact_qty[(item, stage)] = exact_qty.get((item, stage), 0.0) + _f(qty)
		else:
			loose_qty[item] = loose_qty.get(item, 0.0) + _f(qty)
	own = []
	for item, stage, qty, _amount in boq:
		if exact.get((item, stage)):
			pool, shared = exact[(item, stage)], exact_qty[(item, stage)]
		else:
			pool, shared = loose.get(item, 0.0), loose_qty.get(item, 0.0)
		own.append(pool * _f(qty) / shared if pool and shared else 0.0)
	return own


def price_boq(boq, costs, price) -> list:
	"""What each BOQ line sells for so that the BOQ comes to the price.

	Each line gets the share of the price its own cost (see boq_line_costs) is of all their own costs, so the
	costs on no line (labour, tools, freight, overheads) and the margin are spread in proportion: own
	costs 100 and 300, price 625 -> 156.25 and 468.75. A line with no cost of its own cannot be priced
	this way: it keeps its amount, which comes off the price first, and reads None. All read None when
	nothing is left to share.
	"""
	own = boq_line_costs(boq, costs)
	to_share = _f(price) - sum(_f(line[3]) for line, cost in zip(boq, own) if not cost)
	total = sum(own)
	if not total or to_share <= 0:
		return [None] * len(boq)
	return [cost * to_share / total if cost else None for cost in own]


# the sections of a cost estimate and budget, in the order of the business's budget sheets
COST_SECTIONS = (
	"Equipment", "Installation Materials", "Taxes and Freight", "Labour", "Tools and Equipment", "Preliminaries", "Administrative",
)


def section_of_cost_code(cost_code, budget_section=None) -> str | None:
	"""The section a line falls in when none is given, from its cost code: MAT-500 equipment, MAT-600 taxes
	and freight, other MAT codes installation materials, WRK-300 tools, other WRK codes labour, ADM-100 and
	ADM-300 preliminaries, other ADM codes administrative; any other code by its budget section."""
	code = str(cost_code or "").upper()
	if code.startswith("MAT-500"):
		return "Equipment"
	if code.startswith("MAT-600"):
		return "Taxes and Freight"
	if code.startswith("WRK-300"):
		return "Tools and Equipment"
	if code.startswith(("ADM-100", "ADM-300")):
		return "Preliminaries"
	by_prefix = {"MAT": "Installation Materials", "WRK": "Labour", "ADM": "Administrative"}.get(code[:3])
	by_budget = {"Materials": "Installation Materials", "Works": "Labour", "Administrative": "Administrative"}.get(budget_section or "")
	return by_prefix or by_budget


def rate_includes_vat_by_default(section, foreign_currency) -> int:
	"""Local quotations for equipment, materials and tools include VAT; imports, labour and overheads do
	not (as the business's budget sheets have it)."""
	return 1 if section in ("Equipment", "Installation Materials", "Tools and Equipment") and not foreign_currency else 0


def still_needed(plan, unscheduled, paid, current) -> dict:
	"""What a budget's cash plan ({(year, month): amount}, and what it has not scheduled) still needs, once what has been
	paid has covered its earliest months and then what is not scheduled: {now: what is left of the months before the
	current one, months: {(year, month): what is left of it}, unscheduled, total}."""
	left, now, months = _f(paid), 0.0, {}
	for month in sorted(plan):
		need = _f(plan[month])
		covered = min(left, need)
		left -= covered
		need -= covered
		if month < current:
			now += need
		elif need:
			months[month] = need
	unscheduled = max(_f(unscheduled) - left, 0.0)
	return {"now": now, "months": months, "unscheduled": unscheduled, "total": now + sum(months.values()) + unscheduled}


def month_shares(start, end) -> dict:
	"""{(year, month): share} of a period's days that fall in each month, adding up to one: 10 October
	to 9 November -> October 22/31, November 9/31. Without an end, or with the end before the start,
	the period is its first day."""
	start, end = _d(start), _d(end)
	if not start:
		return {}
	if not end or end < start:
		end = start
	days = (end - start).days + 1
	shares, day = {}, start
	while day <= end:
		next_month = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
		last = min(end, next_month - timedelta(days=1))
		shares[(day.year, day.month)] = ((last - day).days + 1) / days
		day = last + timedelta(days=1)
	return shares


def paid_share(total, outstanding) -> float:
	"""Fraction of an invoice that has been settled, clamped to 0..1."""
	total = _f(total)
	if total <= 0:
		return 0.0
	return min(max((total - _f(outstanding)) / total, 0.0), 1.0)


# ------------------------------------------------------------------ accountability
def accountability_position(issued, spent, returned=0) -> dict:
	"""Who owes whom after a cash advance is accounted for.

	Issued more than spent  -> the requester returns the balance to Finance.
	Spent more than issued  -> the company reimburses the requester.
	"""
	issued, spent, returned = _f(issued), _f(spent), _f(returned)
	balance_to_return = max(issued - spent, 0)
	return {
		"balance_to_return": balance_to_return,
		"reimbursement_due": max(spent - issued, 0),
		"balance_outstanding": max(balance_to_return - returned, 0),
	}


# ------------------------------------------------------------------ claims and retention
def claim_valuation(work_done, materials_on_site=0, retention_percent=0, advance_recovery=0, other_deductions=0, advance_claimed=0) -> dict:
	gross = _f(work_done) + _f(materials_on_site) + _f(advance_claimed)
	# retention is held on work and materials, never on the advance itself
	retention = (_f(work_done) + _f(materials_on_site)) * _f(retention_percent) / 100
	net = gross - retention - _f(advance_recovery) - _f(other_deductions)
	return {"gross": gross, "retention": retention, "net": net}


def advance_recovery(gross, advance_percent, advance_total, recovered_to_date) -> float:
	"""Pro-rata recovery of the advance from a certificate, capped at what is still outstanding."""
	remaining = max(_f(advance_total) - _f(recovered_to_date), 0)
	return min(_f(gross) * _f(advance_percent) / 100, remaining)


def retention_release_due(retention_held, released, stage, percent_at_practical=50) -> float:
	"""Retention that falls due at a completion stage.

	Practical completion releases the configured share (normally half); the end of the
	defects liability period releases whatever is still held.
	"""
	held, released = _f(retention_held), _f(released)
	if stage == "Practical Completion":
		due = held * _f(percent_at_practical) / 100 - released
	else:
		due = held - released
	return max(due, 0)


# ------------------------------------------------------------------ approvals
def approval_route(amount, thresholds, risk_class="Any") -> str:
	"""Pick the approval route for a document total.

	thresholds: iterable of dicts with upto_amount, approval_route and optional risk_class.
	A limit for any risk applies to everything but a high-risk document, which only a limit for high risk
	can shorten. The lowest matching limit wins; with no match the full route applies.
	"""
	risks = (risk_class,) if risk_class == "High" else ("Any", risk_class)
	matches = [
		t
		for t in thresholds or []
		if _f(amount) <= _f(t.get("upto_amount"))
		and (t.get("risk_class") or "Any") in risks
	]
	if not matches:
		return FULL_ROUTE
	return min(matches, key=lambda t: _f(t.get("upto_amount"))).get("approval_route") or FULL_ROUTE


def hours_between(start, end) -> float:
	return max((end - start).total_seconds() / 3600, 0)


# ------------------------------------------------------------------ three-way match
def three_way_match(lines, qty_tolerance_percent=0, rate_tolerance_percent=0) -> list[str]:
	"""Compare supplier invoice lines with what was ordered and received.

	lines: dicts with item, billed_qty (this invoice plus earlier ones), ordered_qty,
	received_qty (what was accepted; rejected goods are not owed), invoice_rate, order_rate, has_order,
	needs_receipt.
	Returns one message per exception; an empty list means the invoice matches.
	"""
	exceptions = []
	for line in lines:
		item = line.get("item") or "?"
		if not line.get("has_order"):
			exceptions.append(f"{item}: not linked to a Purchase Order")
			continue
		billed, ordered, received = _f(line.get("billed_qty")), _f(line.get("ordered_qty")), _f(line.get("received_qty"))
		tolerance = 1 + _f(qty_tolerance_percent) / 100
		if billed > ordered * tolerance + 1e-9:
			exceptions.append(f"{item}: invoiced {billed:g} but only {ordered:g} ordered")
		if line.get("needs_receipt", True) and billed > received * tolerance + 1e-9:
			exceptions.append(f"{item}: invoiced {billed:g} but only {received:g} received and accepted")
		order_rate, invoice_rate = _f(line.get("order_rate")), _f(line.get("invoice_rate"))
		if order_rate and invoice_rate > order_rate * (1 + _f(rate_tolerance_percent) / 100) + 1e-9:
			exceptions.append(f"{item}: invoice rate {invoice_rate:,.2f} is above the order rate {order_rate:,.2f}")
	return exceptions


# ------------------------------------------------------------------ progress
def planned_percent(start, end, on_date) -> float:
	"""Straight-line planned progress of an activity on a date."""
	start, end, on_date = _d(start), _d(end), _d(on_date)
	if not start or not end or not on_date or on_date < start:
		return 0.0
	if on_date >= end or end <= start:
		return 100.0
	return round((on_date - start).days / (end - start).days * 100, 2)


def weighted_progress(rows) -> float:
	"""rows: (weight, percent) pairs. Unweighted rows share equally."""
	rows = [(_f(w), _f(p)) for w, p in rows]
	if not rows:
		return 0.0
	total_weight = sum(w for w, _ in rows)
	if total_weight <= 0:
		return round(sum(p for _, p in rows) / len(rows), 2)
	return round(sum(w * p for w, p in rows) / total_weight, 2)


# ------------------------------------------------------------------ the activity schedule
class ScheduleError(Exception):
	"""What is wrong with a schedule: kind is format, unknown or loop, row the ID of the row at fault and text the
	predecessor it names."""

	def __init__(self, kind, row, text=""):
		super().__init__(kind, row, text)
		self.kind, self.row, self.text = kind, row, text


PREDECESSOR = re.compile(r"^(\d+)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+)\s*(d|days?|w|wks?|weeks?)?)?$", re.IGNORECASE)


def add_workdays(day, count=0):
	"""The day count working days on from day, Monday to Friday, back when count is negative. A day at a weekend
	first moves on to the Monday."""
	while day.weekday() > 4:
		day += timedelta(days=1)
	step = timedelta(days=1 if count > 0 else -1)
	for _ in range(abs(int(count))):
		day += step
		while day.weekday() > 4:
			day += step
	return day


def workdays_between(start, end) -> int:
	"""The working days from start to end, both counted; at least one."""
	return max(sum(1 for offset in range((end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5), 1)


def parse_predecessors(text) -> list:
	"""[(ID, kind, lag in working days)] from predecessors as scheduling tools write them: 25,28 or 6SS or 25FS+2 days
	or 31SS+7 days,46SS+7 days. ValueError with the part that reads otherwise."""
	links = []
	for part in re.split(r"[,;]", str(text or "")):
		part = part.strip()
		if not part:
			continue
		found = PREDECESSOR.match(part)
		if not found:
			raise ValueError(part)
		row, kind, sign, lag, unit = found.groups()
		days = int(lag or 0) * (5 if unit and unit[0].lower() == "w" else 1) * (-1 if sign == "-" else 1)
		links.append((int(row), (kind or "FS").upper(), days))
	return links


def write_predecessors(links) -> str:
	"""Predecessors written back the same way."""

	def one(row, kind, lag):
		if not lag:
			return f"{row}{'' if kind == 'FS' else kind}"
		return f"{row}{kind}{lag:+d} day{'' if abs(lag) == 1 else 's'}"

	return ",".join(one(*link) for link in links)


def outline_parents(levels) -> list:
	"""For each row of an outline, the position of the row it sits under (the last one above it at a lesser level),
	or None."""
	parents, open_rows = [], []
	for position, level in enumerate(levels):
		while open_rows and levels[open_rows[-1]] >= level:
			open_rows.pop()
		parents.append(open_rows[-1] if open_rows else None)
		open_rows.append(position)
	return parents


def outline_milestones(levels) -> list:
	"""The positions of an outline's milestones: its top rows, going past a lone row that only wraps sections, such as
	one naming the project and then CONSTRUCTION."""
	children = defaultdict(list)
	for position, parent in enumerate(outline_parents(levels)):
		children[parent].append(position)
	top = children[None]
	while len(top) == 1 and any(children[child] for child in children[top[0]]):
		top = children[top[0]]
	return top


def outline_from_groups(rows) -> tuple:
	"""An outline from each row naming the ID of its group task: the positions of rows in outline order, each under its
	group task in the order given, and each position's level. A row naming none is at the top. ScheduleError for a
	group task that is not in the schedule, or a row that ends up under itself."""
	positions = {row["id"]: place for place, row in enumerate(rows) if row.get("id")}
	under = defaultdict(list)
	for place, row in enumerate(rows):
		group = row.get("group")
		if group and group not in positions:
			raise ScheduleError("group", row.get("id") or place + 1, str(group))
		under[positions[group] if group else None].append(place)
	order, levels = [], {}

	def walk(parent, level):
		for place in under[parent]:
			order.append(place)
			levels[place] = level
			walk(place, level + 1)

	walk(None, 0)
	for place, row in enumerate(rows):
		if place not in levels:
			raise ScheduleError("group-loop", row.get("id") or place + 1)
	return order, levels


def outline_kinds(levels) -> list:
	"""What each row of an outline is: Heading above the milestones, Milestone, Group Task with rows under it, Subtask."""
	parents = outline_parents(levels)
	with_rows = {parent for parent in parents if parent is not None}
	top = set(outline_milestones(levels))
	kinds = []
	for position in range(len(levels)):
		above = position
		while above is not None and above not in top:
			above = parents[above]
		if above is None:
			kinds.append("Heading")
		elif position in top:
			kinds.append("Milestone")
		else:
			kinds.append("Group Task" if position in with_rows else "Subtask")
	return kinds


def work_out_schedule(rows, first_day) -> list:
	"""An outline schedule worked out as a scheduling tool does it, Monday to Friday. rows are {id, level, duration,
	start, end, predecessors} in their order. A row's new ID is its place, its predecessors following (a row moved or
	added keeps its links). A task lasts its duration, or the days from its start to its end, or a day. It starts when
	its predecessors and those of the rows it sits under allow; with none, on its own start, else the nearest above
	it, else first_day. A row with rows under it runs from the first of their starts to the last of their finishes.
	Returns for each row {id, group: the new ID of its group task or 0, level, kind, predecessors, start, end, duration,
	summary, milestone: the position of its milestone, None above the milestones}. ScheduleError for a predecessor
	that reads wrongly, is not in the schedule, or loops."""
	new_ids = {row["id"]: place for place, row in enumerate(rows) if row.get("id")}
	levels = [int(row.get("level") or 0) for row in rows]
	parents = outline_parents(levels)
	children = defaultdict(list)
	for position, parent in enumerate(parents):
		children[parent].append(position)
	links = []
	for position, row in enumerate(rows):
		try:
			parsed = parse_predecessors(row.get("predecessors"))
		except ValueError as error:
			raise ScheduleError("format", position + 1, str(error)) from error
		for other, _kind, _lag in parsed:
			if other not in new_ids:
				raise ScheduleError("unknown", position + 1, str(other))
		links.append([(new_ids[other], kind, lag) for other, kind, lag in parsed])
	started, finished, busy = {}, {}, set()

	def guard(key):
		if key in busy:
			raise ScheduleError("loop", key[1] + 1)
		busy.add(key)

	def days_of(i):
		row = rows[i]
		if int(row.get("duration") or 0) > 0:
			return int(row["duration"])
		if row.get("start") and row.get("end") and row["end"] >= row["start"]:
			return workdays_between(row["start"], row["end"])
		return 1

	def bound(other, kind, lag, i):
		if kind == "SS":
			return add_workdays(start_of(other), lag)
		if kind == "FS":
			return add_workdays(finish_of(other), 1 + lag)
		finish = add_workdays(finish_of(other), lag) if kind == "FF" else add_workdays(start_of(other), lag - 1)
		return add_workdays(finish, 1 - days_of(i))

	def task_start(i):
		bounds, above = [], i
		while above is not None:
			bounds += [bound(other, kind, lag, i) for other, kind, lag in links[above]]
			above = parents[above]
		if bounds:
			return max(bounds)
		above = i
		while above is not None:
			if rows[above].get("start"):
				return add_workdays(rows[above]["start"])
			above = parents[above]
		return add_workdays(first_day)

	def start_of(i):
		if i not in started:
			guard(("start", i))
			started[i] = min(map(start_of, children[i])) if children[i] else task_start(i)
			busy.discard(("start", i))
		return started[i]

	def finish_of(i):
		if i not in finished:
			guard(("finish", i))
			finished[i] = max(map(finish_of, children[i])) if children[i] else add_workdays(start_of(i), days_of(i) - 1)
			busy.discard(("finish", i))
		return finished[i]

	top = set(outline_milestones(levels))
	kinds = outline_kinds(levels)
	out = []
	for i in range(len(rows)):
		milestone = i
		while milestone is not None and milestone not in top:
			milestone = parents[milestone]
		out.append(
			{
				"id": i + 1,
				"group": parents[i] + 1 if parents[i] is not None else 0,
				"level": levels[i],
				"kind": kinds[i],
				"predecessors": write_predecessors([(other + 1, kind, lag) for other, kind, lag in links[i]]),
				"start": start_of(i),
				"end": finish_of(i),
				"duration": workdays_between(start_of(i), finish_of(i)) if children[i] else days_of(i),
				"summary": bool(children[i]),
				"milestone": milestone,
			}
		)
	return out


# ------------------------------------------------------------------ BOQ progress
def share_out(amounts, total) -> list:
	"""A total shared among amounts in proportion, to the cent, the last taking what rounding leaves."""
	whole = sum(_f(amount) for amount in amounts)
	if not whole:
		return [0.0] * len(amounts)
	shares = [round(_f(total) * _f(amount) / whole, 2) for amount in amounts]
	shares[-1] = round(_f(total) - sum(shares[:-1]), 2)
	return shares


def allocate_to_lines(lines, totals) -> dict:
	"""Spread document quantities over BOQ lines.

	lines: [{"name", "item_code", "phase", "qty"}] in BOQ order.
	totals: {(item_code, milestone or None): quantity}.
	A total goes to the lines of the same item and milestone, in order, each line taking up to its
	own quantity and the last one any excess. A total with no milestone, or whose milestone has no
	line for the item, goes to the item's lines without a milestone, else to all its lines, since a BOQ's
	stages need not be the schedule's milestones. Returns {line name: quantity}.
	"""
	groups = {}
	for line in lines:
		groups.setdefault((line["item_code"], line.get("phase") or None), []).append(line)
	result = {line["name"]: 0.0 for line in lines}
	unplaced = {}
	for (item, phase), qty in totals.items():
		target = groups.get((item, phase)) if phase else None
		if target:
			_spread(target, _f(qty), result)
		else:
			unplaced[item] = unplaced.get(item, 0.0) + _f(qty)
	for item, qty in unplaced.items():
		target = groups.get((item, None)) or [line for line in lines if line["item_code"] == item]
		if target:
			_spread(target, qty, result)
	return result


def _spread(lines, qty, result):
	for i, line in enumerate(lines):
		share = qty if i == len(lines) - 1 else min(qty, max(_f(line["qty"]), 0.0))
		result[line["name"]] += share
		qty -= share


# ------------------------------------------------------------------ bids
def margin_percent(price, cost) -> float:
	"""Margin as a share of the price: price 100, cost 80 -> 20.0. Without a price there is none."""
	price = _f(price)
	return (price - _f(cost)) / price * 100 if price else 0.0


def milestone_progress(rows) -> float:
	"""Weight reached out of the weight that applies, in percent. rows: (weight, status) pairs, status
	Pending, Reached or Not Applicable; a milestone that does not apply counts for nothing either way."""
	applying = [(_f(weight), status) for weight, status in rows if status != "Not Applicable"]
	total = sum(weight for weight, _status in applying)
	return sum(weight for weight, status in applying if status == "Reached") / total * 100 if total else 0.0


def price_gap_percent(ours, theirs) -> float:
	"""How much higher our price was than the winning one; negative when ours was lower."""
	ours, theirs = _f(ours), _f(theirs)
	return (ours - theirs) / theirs * 100 if ours and theirs else 0.0
