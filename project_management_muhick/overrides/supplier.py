# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Supplier onboarding: a new supplier carries a list of requirements and cannot be approved
until the mandatory ones are provided. The person who created the supplier cannot approve it."""

import frappe
from frappe import _

from project_management_muhick.utils.common import FM, PRM, get_settings, notify_roles, user_has_any_role

NOT_CLEARED = ("Pending", "Rejected")


def validate(doc, method=None):
	if doc.is_new() and not doc.get("muhick_onboarding_status"):
		_start_onboarding(doc)
	before = doc.get_doc_before_save()
	was_approved = bool(before and before.get("muhick_onboarding_status") == "Approved")
	if doc.get("muhick_onboarding_status") == "Approved" and not was_approved:
		_approve(doc)
	elif doc.get("muhick_onboarding_status") != "Approved":
		doc.muhick_onboarding_approved_by = None


def _start_onboarding(doc):
	requirements = get_settings().get("supplier_onboarding_checklist") or []
	if not requirements:
		doc.muhick_onboarding_status = "Not Required"
		return
	doc.muhick_onboarding_status = "Pending"
	if not doc.get("muhick_onboarding_checklist"):
		for item in requirements:
			doc.append("muhick_onboarding_checklist", {"requirement": item.checklist_item, "is_mandatory": item.is_mandatory})


def _approve(doc):
	if not user_has_any_role(PRM, FM, "System Manager"):
		frappe.throw(_("Only the Procurement Manager or the Finance Manager can approve a supplier."), frappe.PermissionError)
	if doc.owner == frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("You created this supplier, so someone else must approve it."))
	missing = [r.requirement for r in doc.get("muhick_onboarding_checklist") or [] if r.is_mandatory and not r.provided]
	if missing:
		frappe.throw(
			_("These onboarding requirements are still outstanding:") + "<br>" + "<br>".join(f"- {m}" for m in missing),
			title=_("Supplier Onboarding Incomplete"),
		)
	doc.muhick_onboarding_approved_by = frappe.session.user


def after_insert(doc, method=None):
	if doc.get("muhick_onboarding_status") == "Pending":
		notify_roles(
			[PRM, FM], _("New supplier {0} is awaiting onboarding approval.").format(doc.supplier_name), doc=doc
		)


def check_purchase_order(doc, enforce=False):
	"""Warn about, or stop, an order to a supplier whose onboarding is not approved."""
	action = get_settings().supplier_onboarding_action or "Warn"
	if action == "Off" or not doc.supplier:
		return
	status = frappe.db.get_value("Supplier", doc.supplier, "muhick_onboarding_status")
	if status not in NOT_CLEARED:
		return
	message = _("Supplier {0} has not completed onboarding (status: {1}).").format(doc.supplier, _(status))
	if action == "Block" and enforce:
		frappe.throw(message, title=_("Supplier Not Approved"))
	frappe.msgprint(message, indicator="orange", alert=True)
