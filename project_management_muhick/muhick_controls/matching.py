# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Three-way match: Purchase Order vs goods received vs supplier invoice.

Example: order 100 units, receive 80, invoice 100: the invoice is flagged or blocked.
The action is set in Muhick Settings: Off, Warn (flag the invoice) or Block (flag it, put it on
hold and refuse payment until the mismatch is resolved or overridden by an authorised role).

The reserve invoice of an import is booked from the commercial invoice, before the goods arrive, so
it waits for them. Every invoice on an order is matched again when goods are received against it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FM, FO, get_settings, notify_roles, user_has_any_role

HOLD_PREFIX = "Three-way match: "
RESULT_FIELDS = ("muhick_match_status", "muhick_match_remarks", "muhick_match_overridden_by", "on_hold", "hold_comment")


def apply(doc, announce=True):
	"""Purchase Invoice validate."""
	settings = get_settings()
	action = settings.three_way_match_action or "Warn"
	if action == "Off" or doc.is_return or doc.get("muhick_subcontract_agreement"):
		# subcontract work is certified by a Service Receipt Note instead of a goods receipt
		doc.muhick_match_status = "Not Applicable"
		doc.muhick_match_remarks = ""
		return

	lines = _lines(doc)
	exceptions = calc.three_way_match(lines, settings.match_qty_tolerance_percent, settings.match_rate_tolerance_percent)
	remarks = "\n".join(exceptions)

	if not exceptions:
		waiting = any(line.get("awaiting_goods") for line in lines)
		doc.muhick_match_status = "Awaiting Goods" if waiting else "Matched" if lines else "Not Applicable"
		doc.muhick_match_remarks = ""
		_release_hold(doc)
		return

	if doc.get("muhick_match_status") == "Overridden" and doc.get("muhick_match_remarks") == remarks:
		return  # the same exceptions were already reviewed and overridden

	doc.muhick_match_status = "Exception"
	doc.muhick_match_remarks = remarks
	doc.muhick_match_overridden_by = None
	if action == "Block":
		doc.on_hold = 1
		doc.hold_comment = (HOLD_PREFIX + remarks)[:500]
	if announce:
		frappe.msgprint(
			_("This invoice does not match the order and the goods received:") + "<br>" + "<br>".join(exceptions),
			title=_("Three-Way Match Exception"),
			indicator="red" if action == "Block" else "orange",
		)


def recheck_on_receipt(doc, method=None):
	"""Purchase Receipt on_submit and on_cancel: goods have arrived or gone back, so the invoices already posted on those
	order lines are matched again, and a hold follows. Finance is told of a result that changes."""
	order_lines = [row.purchase_order_item for row in doc.items if row.get("purchase_order_item")]
	if not order_lines:
		return
	for name in frappe.get_all(
		"Purchase Invoice Item", filters={"po_detail": ("in", order_lines), "docstatus": 1}, pluck="parent", distinct=True
	):
		invoice = frappe.get_doc("Purchase Invoice", name)
		before = {field: invoice.get(field) for field in RESULT_FIELDS}
		apply(invoice, announce=False)
		changed = {field: invoice.get(field) for field in RESULT_FIELDS if invoice.get(field) != before[field]}
		if changed:
			frappe.db.set_value("Purchase Invoice", name, changed)
		if "muhick_match_status" in changed:
			notify_roles(
				[FM, FO],
				_("{0} was matched again after {1}: {2}.").format(name, doc.name, _(invoice.muhick_match_status)),
				doc=invoice,
			)


def _lines(doc) -> list[dict]:
	lines = []
	orders = {}
	for row in doc.items:
		if not row.item_code:
			continue
		is_stock, is_asset = frappe.get_cached_value("Item", row.item_code, ["is_stock_item", "is_fixed_asset"])
		goods = bool(is_stock or is_asset)
		has_order = bool(row.purchase_order and row.po_detail)
		if not has_order and not goods:
			continue  # services and expenses bought without an order (utilities, fees) are not matched
		line = {
			"item": row.item_code,
			"has_order": has_order,
			# an invoice that also receives the stock is its own goods receipt
			"needs_receipt": goods and not doc.get("update_stock"),
			"invoice_rate": flt(row.base_rate),
		}
		if has_order:
			po = frappe.db.get_value("Purchase Order Item", row.po_detail, ["qty", "rate", "base_rate", "parent"], as_dict=True)
			if not po:
				line["has_order"] = False
			else:
				if po.parent not in orders:
					orders[po.parent] = frappe.db.get_value(
						"Purchase Order", po.parent, ["currency", "muhick_procurement_type"], as_dict=True
					)
				order = orders[po.parent]
				# in the order's own currency where the invoice is in it too, so a change in the exchange rate does not trip it
				same_currency = order.currency == doc.get("currency")
				received = _accepted_qty(row.po_detail)
				line.update(
					ordered_qty=flt(po.qty),
					received_qty=received,
					order_rate=flt(po.rate if same_currency else po.base_rate),
					invoice_rate=flt(row.rate if same_currency else row.base_rate),
					billed_qty=_billed_before(row.po_detail, doc.name) + flt(row.qty),
				)
				if line["needs_receipt"] and not received and order.muhick_procurement_type == "International":
					line.update(needs_receipt=False, awaiting_goods=True)
		lines.append(line)
	return lines


def _accepted_qty(po_detail) -> float:
	"""What was accepted against an order line: goods received notes less their returns, and invoices that
	also received the stock. The order's own received quantity counts rejected goods too, which are not owed."""
	accepted = frappe.db.sql(
		"""
		select sum(qty) from (
			select pri.qty from `tabPurchase Receipt Item` pri
			where pri.purchase_order_item = %(row)s and pri.docstatus = 1
			union all
			select pii.qty from `tabPurchase Invoice Item` pii
			inner join `tabPurchase Invoice` pi on pi.name = pii.parent
			where pii.po_detail = %(row)s and pi.docstatus = 1 and pi.update_stock = 1
		) accepted
		""",
		{"row": po_detail},
	)
	return flt(accepted[0][0]) if accepted else 0.0


def _billed_before(po_detail, this_invoice) -> float:
	billed = frappe.db.sql(
		"""
		select sum(pii.qty) from `tabPurchase Invoice Item` pii
		inner join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pii.po_detail = %s and pi.docstatus = 1 and pi.name != %s
		""",
		(po_detail, this_invoice or ""),
	)
	return flt(billed[0][0]) if billed else 0.0


def _release_hold(doc):
	if doc.get("on_hold") and (doc.get("hold_comment") or "").startswith(HOLD_PREFIX):
		doc.on_hold = 0
		doc.hold_comment = None


def is_blocked(purchase_invoice) -> bool:
	if (get_settings().three_way_match_action or "Warn") != "Block":
		return False
	return frappe.db.get_value("Purchase Invoice", purchase_invoice, "muhick_match_status") == "Exception"


@frappe.whitelist()
def override(purchase_invoice: str, reason: str):
	"""An authorised role accepts a mismatch (for example a supplier's partial stock-out)."""
	role = get_settings().three_way_match_override_role
	if not role or not user_has_any_role(role, "System Manager"):
		frappe.throw(_("You are not allowed to override a three-way match exception."), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for the override."))
	doc = frappe.get_doc("Purchase Invoice", purchase_invoice)
	doc.check_permission("write")
	if doc.get("muhick_match_status") != "Exception":
		frappe.throw(_("This invoice has no open match exception."))
	values = {"muhick_match_status": "Overridden", "muhick_match_overridden_by": frappe.session.user}
	if (doc.get("hold_comment") or "").startswith(HOLD_PREFIX):
		values.update(on_hold=0, hold_comment=None)
	frappe.db.set_value("Purchase Invoice", purchase_invoice, values)
	doc.add_comment("Info", _("Three-way match exception overridden by {0}: {1}").format(frappe.session.user, reason))
	return "Overridden"
