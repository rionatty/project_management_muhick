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

	def test_budget_status(self):
		self.assertEqual(calc.budget_status(30, 30), "Within Budget")
		self.assertEqual(calc.budget_status(30.01, 30), "Exceeds Budget")
		self.assertEqual(calc.budget_status(1, 0, budgeted=False), "Not Budgeted")

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
		self.assertEqual(calc.approval_route(1_500_000, self.THRESHOLDS, "High"), calc.SECOND_APPROVER)


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


if __name__ == "__main__":
	unittest.main()
