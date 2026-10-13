# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Pure calculations used across the app.

Nothing in this module imports frappe, so the rules can be unit tested without a site.
"""

from datetime import date, datetime

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
	The lowest matching limit wins; with no match the full route applies.
	"""
	matches = [
		t
		for t in thresholds or []
		if _f(amount) <= _f(t.get("upto_amount"))
		and (t.get("risk_class") or "Any") in ("Any", risk_class)
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
	received_qty, invoice_rate, order_rate, has_order, needs_receipt.
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
			exceptions.append(f"{item}: invoiced {billed:g} but only {received:g} received")
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
