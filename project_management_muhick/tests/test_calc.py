# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Rule tests that need no site: python -m unittest project_management_muhick.tests.test_calc"""

import importlib.util
import os
import unittest

# load calc.py by path so the tests also run outside a bench (no frappe import needed)
_spec = importlib.util.spec_from_file_location(
	"muhick_calc", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "utils", "calc.py")
)
calc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calc)


class TestBudget(unittest.TestCase):
	def test_commitment_reduces_available_budget_before_payment(self):
		# budget 300m, PO committed 270m, paid 80m -> 30m available, not 220m
		self.assertEqual(calc.available_budget(300_000_000, 270_000_000), 30_000_000)

	def test_forecast_defaults_to_budget_until_overcommitted(self):
		self.assertEqual(calc.forecast_final_cost(300, 270), 300)
		self.assertEqual(calc.forecast_final_cost(300, 320), 320)

	def test_forecast_uses_manual_estimate_to_complete(self):
		self.assertEqual(calc.forecast_final_cost(300, 270, 50), 320)
		self.assertEqual(calc.forecast_final_cost(300, 270, 0), 270)


class TestCostLines(unittest.TestCase):
	def test_people_by_qty_by_rate(self):
		# 4 plumbers for 3 months at 1.5m a month
		self.assertEqual(calc.line_amount(3, 1_500_000, people=4), 18_000_000)

	def test_foreign_currency_at_the_line_rate(self):
		self.assertEqual(calc.line_amount(2, 10_000, exchange_rate=3_700), 74_000_000)

	def test_rate_quoted_with_vat_is_taken_without_it(self):
		self.assertAlmostEqual(calc.line_amount(10, 118, includes_vat=True, vat_percent=18), 1_000)
		self.assertEqual(calc.line_amount(10, 118, vat_percent=18), 1_180)

	def test_share_of_the_contract_value(self):
		self.assertEqual(calc.line_amount(5, 100, contract_percent=1, contract_value=2_000_000_000), 20_000_000)

	def test_people_and_exchange_rate_at_zero_count_as_one(self):
		self.assertEqual(calc.line_amount(2, 50, people=0, exchange_rate=0), 100)

	def test_import_taxes_as_the_tax_computation(self):
		taxes = calc.import_taxes(6_720, insurance_percent=1.5, duty_percent=10, vat_percent=18, levy_percent=1.5)
		self.assertAlmostEqual(taxes["insurance"], 100.8)
		self.assertAlmostEqual(taxes["customs_value"], 6_820.8)
		self.assertAlmostEqual(taxes["duty"], 682.08)
		self.assertAlmostEqual(taxes["vat"], 1_350.52, places=2)
		self.assertAlmostEqual(taxes["levy"], 102.31, places=2)
		self.assertAlmostEqual(taxes["total_tax"], 2_134.91, places=2)
		self.assertAlmostEqual(taxes["cost"], 100.8 + 682.08 + 102.312, places=2)

	def test_goods_from_the_community_pay_vat_only(self):
		taxes = calc.import_taxes(12_554, vat_percent=18)
		self.assertAlmostEqual(taxes["total_tax"], 2_259.72)
		self.assertEqual(taxes["cost"], 0)

	def test_price_for_a_margin(self):
		self.assertAlmostEqual(calc.price_for_margin(930, 7), 1_000)
		self.assertAlmostEqual(calc.price_for_margin(1_000_000_000, 7), 1_075_268_817.2, places=1)

	def test_a_share_of_the_contract_rises_with_the_price(self):
		self.assertAlmostEqual(calc.price_for_margin(920, 7, 1), 1_000)

	def test_a_margin_leaving_nothing_gives_no_price(self):
		self.assertIsNone(calc.price_for_margin(100, 100))
		self.assertIsNone(calc.price_for_margin(100, 95, 5))

	def test_boq_priced_in_proportion_to_its_own_costs(self):
		boq = [("PUMP", "Water", 2, 0), ("PIPE", "Water", 30, 0)]
		costs = [("PUMP", "Water", 100), ("PIPE", "Water", 300)]
		self.assertEqual(calc.boq_line_costs(boq, costs), [100, 300])
		self.assertEqual(calc.share_out([300, 200], 250), [150.0, 100.0])
		self.assertEqual(calc.share_out([1, 1, 1], 100), [33.33, 33.33, 33.34])
		self.assertEqual(calc.share_out([0, 0], 100), [0.0, 0.0])
		amounts = calc.price_boq(boq, costs, 625)
		self.assertAlmostEqual(amounts[0], 156.25)
		self.assertAlmostEqual(amounts[1], 468.75)
		self.assertAlmostEqual(sum(amounts), 625)

	def test_lines_of_one_item_and_stage_share_its_cost_by_qty(self):
		boq = [("PIPE", "Water", 10, 0), ("PIPE", "Water", 30, 0)]
		amounts = calc.price_boq(boq, [("PIPE", "Water", 400)], 800)
		self.assertAlmostEqual(amounts[0], 200)
		self.assertAlmostEqual(amounts[1], 600)

	def test_a_cost_in_another_stage_still_counts_for_its_item(self):
		amounts = calc.price_boq([("PIPE", "Water", 10, 0)], [("PIPE", None, 100), ("PIPE", "Fire", 100)], 500)
		self.assertAlmostEqual(amounts[0], 500)

	def test_a_line_with_no_cost_keeps_its_amount(self):
		boq = [("PUMP", "Water", 1, 0), ("SERVICE", "Water", 1, 100)]
		amounts = calc.price_boq(boq, [("PUMP", "Water", 200)], 600)
		self.assertAlmostEqual(amounts[0], 500)
		self.assertIsNone(amounts[1])

	def test_nothing_to_share_prices_no_line(self):
		self.assertEqual(calc.price_boq([("A", None, 1, 0)], [("B", None, 100)], 100), [None])
		self.assertEqual(calc.price_boq([("A", None, 1, 0), ("B", None, 1, 500)], [("A", None, 100)], 400), [None, None])

	def test_section_from_the_cost_code(self):
		self.assertEqual(calc.section_of_cost_code("MAT-500"), "Equipment")
		self.assertEqual(calc.section_of_cost_code("MAT-100"), "Installation Materials")
		self.assertEqual(calc.section_of_cost_code("MAT-600"), "Taxes and Freight")
		self.assertEqual(calc.section_of_cost_code("WRK-150"), "Labour")
		self.assertEqual(calc.section_of_cost_code("WRK-300"), "Tools and Equipment")
		self.assertEqual(calc.section_of_cost_code("ADM-300"), "Preliminaries")
		self.assertEqual(calc.section_of_cost_code("ADM-500"), "Administrative")
		self.assertEqual(calc.section_of_cost_code("FIRE-01", "Materials"), "Installation Materials")
		self.assertIsNone(calc.section_of_cost_code(None))

	def test_vat_in_local_quotes_for_goods_only(self):
		self.assertEqual(calc.rate_includes_vat_by_default("Installation Materials", False), 1)
		self.assertEqual(calc.rate_includes_vat_by_default("Equipment", True), 0)
		self.assertEqual(calc.rate_includes_vat_by_default("Labour", False), 0)

	def test_month_shares(self):
		shares = calc.month_shares("2026-10-10", "2026-11-09")
		self.assertAlmostEqual(shares[(2026, 10)], 22 / 31)
		self.assertAlmostEqual(shares[(2026, 11)], 9 / 31)
		self.assertEqual(set(calc.month_shares("2026-12-20", "2027-01-10")), {(2026, 12), (2027, 1)})
		self.assertEqual(calc.month_shares("2026-10-05", None), {(2026, 10): 1.0})
		self.assertEqual(calc.month_shares(None, "2026-10-05"), {})

	def test_budget_status(self):
		self.assertEqual(calc.budget_status(30, 30), "Within Budget")
		self.assertEqual(calc.budget_status(30.01, 30), "Exceeds Budget")
		self.assertEqual(calc.budget_status(1, 0, budgeted=False), "Not Budgeted")

	def test_budget_line_quantity(self):
		self.assertEqual(calc.budget_line_quantity(10, 3), 30)
		self.assertEqual(calc.budget_line_quantity(10, 0), 10)
		self.assertEqual(calc.budget_line_quantity(1, 1, 5), 0)

	def test_quantity_excess(self):
		budgeted = {"A": 100, "B": 50}
		self.assertEqual(calc.quantity_excess(budgeted, {"A": 80}, {"A": 20}), {})
		self.assertEqual(calc.quantity_excess(budgeted, {"A": 80}, {"A": 21}), {"A": 101})
		# not budgeted by item: left to the check of its cost code's value
		self.assertEqual(calc.quantity_excess(budgeted, {}, {"C": 999}), {})
		# an item already over, which this document adds nothing to
		self.assertEqual(calc.quantity_excess(budgeted, {"B": 70}, {"A": 1}), {})

	def test_beyond_requests(self):
		self.assertEqual(calc.beyond_requests([("A", 60, "r1")], {"r1": 100}), {})
		self.assertEqual(calc.beyond_requests([("A", 60, "r1"), ("A", 60, "r1")], {"r1": 100}), {"A": 20})
		self.assertEqual(calc.beyond_requests([("A", 5, None)], {}), {"A": 5})
		self.assertEqual(calc.beyond_requests([("A", 5, "not approved")], {}), {"A": 5})

	def test_paid_share_is_clamped(self):
		self.assertEqual(calc.paid_share(100, 20), 0.8)
		self.assertEqual(calc.paid_share(100, 120), 0.0)
		self.assertEqual(calc.paid_share(100, -5), 1.0)
		self.assertEqual(calc.paid_share(0, 0), 0.0)


class TestAccountability(unittest.TestCase):
	def test_issued_more_than_spent_returns_balance(self):
		# the requester returns what was not spent
		pos = calc.accountability_position(issued=500_000, spent=420_000)
		self.assertEqual(pos["balance_to_return"], 80_000)
		self.assertEqual(pos["reimbursement_due"], 0)

	def test_spent_more_than_issued_reimburses_requester(self):
		pos = calc.accountability_position(issued=500_000, spent=560_000)
		self.assertEqual(pos["balance_to_return"], 0)
		self.assertEqual(pos["reimbursement_due"], 60_000)

	def test_partial_return_leaves_balance_outstanding(self):
		pos = calc.accountability_position(issued=500_000, spent=420_000, returned=50_000)
		self.assertEqual(pos["balance_outstanding"], 30_000)


class TestClaims(unittest.TestCase):
	def test_claim_valuation(self):
		v = calc.claim_valuation(work_done=100_000_000, retention_percent=10, advance_recovery=30_000_000)
		self.assertEqual(v["gross"], 100_000_000)
		self.assertEqual(v["retention"], 10_000_000)
		self.assertEqual(v["net"], 60_000_000)

	def test_no_retention_on_advance(self):
		v = calc.claim_valuation(work_done=0, advance_claimed=30_000_000, retention_percent=10)
		self.assertEqual(v["retention"], 0)
		self.assertEqual(v["net"], 30_000_000)

	def test_advance_recovery_is_capped(self):
		self.assertEqual(calc.advance_recovery(100, 30, advance_total=300, recovered_to_date=0), 30)
		self.assertEqual(calc.advance_recovery(100, 30, advance_total=300, recovered_to_date=290), 10)
		self.assertEqual(calc.advance_recovery(100, 30, advance_total=300, recovered_to_date=300), 0)

	def test_retention_released_half_then_rest(self):
		self.assertEqual(calc.retention_release_due(100, 0, "Practical Completion", 50), 50)
		self.assertEqual(calc.retention_release_due(100, 50, "Practical Completion", 50), 0)
		self.assertEqual(calc.retention_release_due(100, 50, "End of Defects Liability", 50), 50)


class TestApprovals(unittest.TestCase):
	THRESHOLDS = [
		{"upto_amount": 500_000, "approval_route": calc.FIRST_APPROVER},
		{"upto_amount": 5_000_000, "approval_route": calc.SECOND_APPROVER},
		{"upto_amount": 2_000_000, "approval_route": calc.FIRST_APPROVER, "risk_class": "Low"},
	]

	def test_no_thresholds_means_full_route(self):
		self.assertEqual(calc.approval_route(1, []), calc.FULL_ROUTE)

	def test_lowest_matching_limit_wins(self):
		self.assertEqual(calc.approval_route(400_000, self.THRESHOLDS), calc.FIRST_APPROVER)
		self.assertEqual(calc.approval_route(3_000_000, self.THRESHOLDS), calc.SECOND_APPROVER)
		self.assertEqual(calc.approval_route(9_000_000, self.THRESHOLDS), calc.FULL_ROUTE)

	def test_risk_specific_limit(self):
		self.assertEqual(calc.approval_route(1_500_000, self.THRESHOLDS, "Low"), calc.FIRST_APPROVER)
		self.assertEqual(calc.approval_route(1_500_000, self.THRESHOLDS, "Medium"), calc.SECOND_APPROVER)

	def test_high_risk_only_follows_limits_for_high_risk(self):
		self.assertEqual(calc.approval_route(100, self.THRESHOLDS, "High"), calc.FULL_ROUTE)
		limits = [*self.THRESHOLDS, {"upto_amount": 1_000, "approval_route": calc.SECOND_APPROVER, "risk_class": "High"}]
		self.assertEqual(calc.approval_route(100, limits, "High"), calc.SECOND_APPROVER)
		self.assertEqual(calc.approval_route(2_000, limits, "High"), calc.FULL_ROUTE)


class TestThreeWayMatch(unittest.TestCase):
	def line(self, **kw):
		base = dict(item="PIPE-25", billed_qty=100, ordered_qty=100, received_qty=100, invoice_rate=10, order_rate=10, has_order=True, needs_receipt=True)
		base.update(kw)
		return base

	def test_clean_match(self):
		self.assertEqual(calc.three_way_match([self.line()]), [])

	def test_invoice_exceeds_receipt(self):
		# PO 100, received 80, invoice 100 must be flagged
		exceptions = calc.three_way_match([self.line(received_qty=80)])
		self.assertEqual(len(exceptions), 1)
		self.assertIn("only 80 received", exceptions[0])

	def test_invoice_exceeds_order_and_rate(self):
		exceptions = calc.three_way_match([self.line(billed_qty=120, received_qty=120, invoice_rate=12)])
		self.assertEqual(len(exceptions), 2)

	def test_tolerance(self):
		self.assertEqual(calc.three_way_match([self.line(billed_qty=102, received_qty=102)], qty_tolerance_percent=2), [])

	def test_service_line_needs_no_receipt(self):
		self.assertEqual(calc.three_way_match([self.line(received_qty=0, needs_receipt=False)]), [])

	def test_invoice_without_order(self):
		self.assertEqual(len(calc.three_way_match([self.line(has_order=False)])), 1)


class TestProgress(unittest.TestCase):
	def test_planned_percent(self):
		self.assertEqual(calc.planned_percent("2026-01-01", "2026-01-11", "2026-01-06"), 50.0)
		self.assertEqual(calc.planned_percent("2026-01-01", "2026-01-11", "2025-12-31"), 0.0)
		self.assertEqual(calc.planned_percent("2026-01-01", "2026-01-11", "2026-02-01"), 100.0)

	def test_weighted_progress(self):
		self.assertEqual(calc.weighted_progress([(60, 100), (40, 50)]), 80.0)
		self.assertEqual(calc.weighted_progress([(0, 100), (0, 50)]), 75.0)
		self.assertEqual(calc.weighted_progress([]), 0.0)


class TestBoqProgress(unittest.TestCase):
	@staticmethod
	def line(name, item="X", phase=None, qty=100):
		return {"name": name, "item_code": item, "phase": phase, "qty": qty}

	def test_lines_of_one_item_fill_in_order(self):
		lines = [self.line("a"), self.line("b")]
		self.assertEqual(calc.allocate_to_lines(lines, {("X", None): 150}), {"a": 100, "b": 50})

	def test_milestones_keep_their_own_quantities(self):
		lines = [self.line("a", phase="P1", qty=50), self.line("b", phase="P2", qty=50)]
		totals = {("X", "P1"): 30, ("X", "P2"): 70}
		self.assertEqual(calc.allocate_to_lines(lines, totals), {"a": 30, "b": 70})

	def test_unmatched_quantities_go_to_lines_without_a_milestone(self):
		lines = [self.line("a", phase="P1"), self.line("c")]
		totals = {("X", "P1"): 10, ("X", None): 20, ("X", "P3"): 5, ("Y", None): 7}
		self.assertEqual(calc.allocate_to_lines(lines, totals), {"a": 10, "c": 25})



class TestBids(unittest.TestCase):
	def test_margin_is_a_share_of_the_price(self):
		self.assertEqual(calc.margin_percent(100, 80), 20)
		self.assertEqual(calc.margin_percent(100, 125), -25)

	def test_no_margin_without_a_price(self):
		self.assertEqual(calc.margin_percent(0, 50), 0)

	def test_progress_is_the_weight_reached_of_the_weight_that_applies(self):
		rows = [(10, "Reached"), (30, "Pending"), (60, "Not Applicable")]
		self.assertEqual(calc.milestone_progress(rows), 25)
		self.assertEqual(calc.milestone_progress([(50, "Reached"), (50, "Reached")]), 100)
		self.assertEqual(calc.milestone_progress([(20, "Not Applicable")]), 0)

	def test_price_gap_to_the_winner(self):
		# we bid 110 against a winning 100: 10% above; 90 against 100: 10% below
		self.assertEqual(calc.price_gap_percent(110, 100), 10)
		self.assertEqual(calc.price_gap_percent(90, 100), -10)
		self.assertEqual(calc.price_gap_percent(110, 0), 0)

class TestSchedule(unittest.TestCase):
	ROWS = [
		dict(level=0), dict(level=1), dict(level=2), dict(level=3, duration=5, start=calc.date(2026, 3, 2)), dict(level=3, duration=3, predecessors="4"),
		dict(level=2, predecessors="3"), dict(level=3, duration=10), dict(level=3, duration=5, predecessors="7FS+2 days"), dict(level=3, duration=2, predecessors="8SS"),
	]

	def rows(self):
		return [dict(row, id=i) for i, row in enumerate(self.ROWS, 1)]

	def worked(self):
		return calc.work_out_schedule(self.rows(), calc.date(2026, 1, 5))

	def test_working_days_run_monday_to_friday(self):
		self.assertEqual(calc.add_workdays(calc.date(2026, 3, 6), 1), calc.date(2026, 3, 9))
		self.assertEqual(calc.add_workdays(calc.date(2026, 3, 9), -1), calc.date(2026, 3, 6))
		self.assertEqual(calc.add_workdays(calc.date(2026, 3, 7)), calc.date(2026, 3, 9))
		self.assertEqual(calc.workdays_between(calc.date(2026, 3, 2), calc.date(2026, 3, 9)), 6)

	def test_predecessors_read_and_write_as_scheduling_tools_do(self):
		for text, links in (
			("25,28", [(25, "FS", 0), (28, "FS", 0)]), ("6SS", [(6, "SS", 0)]), ("25FS+2 days", [(25, "FS", 2)]),
			("31SS+7 days,46SS+7 days", [(31, "SS", 7), (46, "SS", 7)]),
		):
			self.assertEqual(calc.parse_predecessors(text), links)
			self.assertEqual(calc.write_predecessors(links), text)
		self.assertEqual(calc.parse_predecessors("3 ss + 1 wk; 4ff-2d"), [(3, "SS", 5), (4, "FF", -2)])
		self.assertEqual(calc.parse_predecessors(None), [])
		with self.assertRaises(ValueError):
			calc.parse_predecessors("after the slab")

	def test_rows_above_the_milestones_only_wrap_them(self):
		self.assertEqual(calc.outline_parents([0, 1, 2, 3, 3, 2, 3]), [None, 0, 1, 2, 2, 1, 5])
		self.assertEqual(calc.outline_milestones([0, 1, 2, 3, 3, 2, 3]), [2, 5])
		self.assertEqual(calc.outline_milestones([0, 1, 0, 1]), [0, 2])
		self.assertEqual(calc.outline_milestones([0, 1, 1]), [0])
		self.assertEqual(calc.outline_milestones([]), [])

	def test_dates_follow_durations_and_predecessors(self):
		worked = self.worked()
		self.assertEqual((worked[3]["start"], worked[3]["end"]), (calc.date(2026, 3, 2), calc.date(2026, 3, 6)))
		self.assertEqual((worked[4]["start"], worked[4]["end"]), (calc.date(2026, 3, 9), calc.date(2026, 3, 11)))
		# a task with no predecessor of its own starts when the section it sits under may
		self.assertEqual((worked[6]["start"], worked[6]["end"]), (calc.date(2026, 3, 12), calc.date(2026, 3, 25)))
		self.assertEqual((worked[7]["start"], worked[7]["end"]), (calc.date(2026, 3, 30), calc.date(2026, 4, 3)))
		self.assertEqual((worked[8]["start"], worked[8]["end"]), (calc.date(2026, 3, 30), calc.date(2026, 3, 31)))

	def test_a_section_runs_over_what_is_under_it(self):
		worked = self.worked()
		self.assertEqual((worked[5]["start"], worked[5]["end"], worked[5]["duration"], worked[5]["summary"]), (calc.date(2026, 3, 12), calc.date(2026, 4, 3), 17, True))
		self.assertEqual([row["milestone"] for row in worked], [None, None, 2, 2, 2, 5, 5, 5, 5])

	def test_ids_follow_the_order_and_links_follow_the_ids(self):
		rows = self.rows()
		rows.insert(4, dict(level=3, duration=1, start=calc.date(2026, 3, 2)))
		worked = calc.work_out_schedule(rows, calc.date(2026, 1, 5))
		self.assertEqual([row["id"] for row in worked], list(range(1, 11)))
		self.assertEqual([row["predecessors"] for row in worked][5:], ["4", "3", "", "8FS+2 days", "9SS"])

	def test_a_task_with_nothing_to_go_on_starts_on_the_first_day(self):
		worked = calc.work_out_schedule([dict(id=1, level=0, duration=2)], calc.date(2026, 1, 3))
		self.assertEqual((worked[0]["start"], worked[0]["end"]), (calc.date(2026, 1, 5), calc.date(2026, 1, 6)))

	def test_a_duration_comes_from_the_dates_when_none_is_given(self):
		worked = calc.work_out_schedule([dict(id=1, level=0, start=calc.date(2026, 3, 2), end=calc.date(2026, 3, 9))], calc.date(2026, 1, 5))
		self.assertEqual((worked[0]["duration"], worked[0]["end"]), (6, calc.date(2026, 3, 9)))

	def test_a_row_names_its_group_task_and_the_outline_follows(self):
		rows = [dict(id=1), dict(id=2, group=3), dict(id=3), dict(id=4, group=1), dict(id=5, group=2), dict(id=6, group=3)]
		order, levels = calc.outline_from_groups(rows)
		self.assertEqual(order, [0, 3, 2, 1, 4, 5])
		self.assertEqual([levels[place] for place in order], [0, 1, 0, 1, 2, 1])
		# a subtask typed above its group task goes under it
		order, levels = calc.outline_from_groups([dict(id=1, group=2), dict(id=2)])
		self.assertEqual((order, levels), ([1, 0], {1: 0, 0: 1}))

	def test_a_group_task_that_cannot_be_is_refused(self):
		for rows, kind in (
			([dict(id=1, group=9)], "group"),
			([dict(id=1, group=1)], "group-loop"),
			([dict(id=1, group=2), dict(id=2, group=1)], "group-loop"),
		):
			with self.assertRaises(calc.ScheduleError) as caught:
				calc.outline_from_groups(rows)
			self.assertEqual(caught.exception.kind, kind)

	def test_each_row_says_what_it_is(self):
		self.assertEqual(calc.outline_kinds([0, 1, 2, 3, 3, 2, 3, 4]), ["Heading", "Heading", "Milestone", "Subtask", "Subtask", "Milestone", "Group Task", "Subtask"])
		self.assertEqual(calc.outline_kinds([0, 0]), ["Milestone", "Milestone"])
		self.assertEqual(calc.outline_kinds([0, 1, 1]), ["Milestone", "Subtask", "Subtask"])
		worked = self.worked()
		self.assertEqual((worked[3]["group"], worked[3]["level"], worked[3]["kind"]), (3, 3, "Subtask"))
		self.assertEqual((worked[0]["group"], worked[0]["kind"]), (0, "Heading"))

	def test_a_schedule_that_cannot_work_is_refused(self):
		for rows, kind, row in (
			([dict(id=1, level=0, predecessors="what")], "format", 1),
			([dict(id=1, level=0, predecessors="9")], "unknown", 1),
			([dict(id=1, level=0, predecessors="2"), dict(id=2, level=0, predecessors="1")], "loop", 1),
			([dict(id=1, level=0, predecessors="1")], "loop", 1),
			([dict(id=1, level=0), dict(id=2, level=1, predecessors="1")], "loop", 2),
		):
			with self.assertRaises(calc.ScheduleError) as caught:
				calc.work_out_schedule(rows, calc.date(2026, 1, 5))
			self.assertEqual(caught.exception.kind, kind)


if __name__ == "__main__":
	unittest.main()
