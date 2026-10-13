# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Three-way match: Purchase Order vs goods received vs supplier invoice.

Example: order 100 units, receive 80, invoice 100: the invoice is flagged or blocked.
The action is set in Muhick Settings: Off, Warn (flag the invoice) or Block (flag it, put it on
hold and refuse payment until the mismatch is resolved or overridden by an authorised role).
"""

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.utils import calc
from project_management_muhick.utils.common import get_settings, user_has_any_role

HOLD_PREFIX = "Three-way match: "


def apply(doc):
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
		doc.muhick_match_status = "Matched" if lines else "Not Applicable"
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
	frappe.msgprint(
		_("This invoice does not match the order and the goods received:") + "<br>" + "<br>".join(exceptions),
		title=_("Three-Way Match Exception"),
		indicator="red" if action == "Block" else "orange",
	)


def _lines(doc) -> list[dict]:
	lines = []
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
			po = frappe.db.get_value("Purchase Order Item", row.po_detail, ["qty", "received_qty", "base_rate"], as_dict=True)
			if not po:
				line["has_order"] = False
			else:
				line.update(
					ordered_qty=flt(po.qty),
					received_qty=flt(po.received_qty),
					order_rate=flt(po.base_rate),
					billed_qty=_billed_before(row.po_detail, doc.name) + flt(row.qty),
				)
		lines.append(line)
	return lines


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
