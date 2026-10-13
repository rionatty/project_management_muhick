# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Stock Entry, Delivery Note and Warehouse hooks: site stores, quarantine and store charges."""

import frappe
from frappe import _

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.utils.common import get_settings, user_has_any_role

SITE_TYPES = ("Site Store", "Client Store")


def _warehouse(name) -> frappe._dict:
	if not name:
		return frappe._dict()
	values = frappe.get_cached_value("Warehouse", name, ["muhick_store_type", "muhick_project", "muhick_stock_ownership"])
	return frappe._dict(store_type=values[0], project=values[1], ownership=values[2])


# ------------------------------------------------------------------ Stock Entry
def validate_stock_entry(doc, method=None):
	_block_quarantine(doc, [(row.s_warehouse, row.t_warehouse) for row in doc.items])
	doc.muhick_approval_route = _approval_route(doc)
	origin = _origin_warehouse(doc)
	for row in doc.items:
		source, target = _warehouse(row.s_warehouse), _warehouse(row.t_warehouse)
		_set_project_from_site_store(doc, row, source)
		project = _charged_project(doc, row, source, target)
		if project and not row.get("muhick_cost_code") and row.item_code:
			row.muhick_cost_code = _cost_code_from_request(row) or budget_engine.get_budget_cost_code(project, row.item_code)
		if doc.is_new():
			# default once; after that the user's tick or untick is kept
			bought_for_project = bool(doc.get("muhick_purchase_order"))
			row.muhick_charge_to_project = int(
				bool(project) and not bought_for_project and _is_company_stock(origin or row.s_warehouse)
			)


def _approval_route(doc) -> str:
	"""Who must approve this entry before it is submitted; blank when nobody needs to.

	A disposal of damaged, expired or obsolete stock needs Finance. A return of materials from a
	site store needs the Procurement Manager (the second leg, out of transit, does not)."""
	if doc.purpose != "Material Issue":
		doc.muhick_is_disposal = 0
	if doc.get("muhick_is_disposal"):
		if not (doc.get("muhick_disposal_reason") or "").strip():
			frappe.throw(_("Give the reason this stock is being disposed of."))
		return "Finance"
	if doc.purpose == "Material Transfer" and not doc.get("outgoing_stock_entry"):
		for row in doc.items:
			source, target = _warehouse(row.s_warehouse), _warehouse(row.t_warehouse)
			same_project_store = target.store_type in SITE_TYPES and target.project == source.project
			if source.store_type in SITE_TYPES and not same_project_store:
				return "Procurement Manager"
	return ""


def _set_project_from_site_store(doc, row, source):
	"""Material issued out of a project's site store is consumed on that project."""
	if doc.purpose == "Material Issue" and source.store_type in SITE_TYPES and source.project:
		if row.project and row.project != source.project:
			frappe.throw(
				_("Row {0}: {1} is the site store of project {2}; its stock cannot be issued to project {3}. Transfer it first.").format(
					row.idx, row.s_warehouse, source.project, row.project
				)
			)
		row.project = source.project
		if not doc.project:
			doc.project = source.project


def _charged_project(doc, row, source, target):
	"""Project that takes the cost of this row when stock is drawn from outside its own store."""
	if doc.purpose == "Material Transfer" and target.store_type in SITE_TYPES and target.project:
		return target.project if source.project != target.project else None
	if doc.purpose == "Material Issue":
		project = row.project or doc.project
		return project if project and source.project != project else None
	return None


def _origin_warehouse(doc):
	"""For the second leg of a transfer through Goods in Transit, the store the stock left from."""
	if doc.get("outgoing_stock_entry"):
		return frappe.db.get_value(
			"Stock Entry Detail", {"parent": doc.outgoing_stock_entry}, "s_warehouse", order_by="idx asc"
		)
	return None


def _is_company_stock(warehouse) -> bool:
	w = _warehouse(warehouse)
	return w.store_type == "Central Store" or w.ownership == "Company"


def _cost_code_from_request(row):
	if row.get("material_request_item"):
		return frappe.db.get_value("Material Request Item", row.material_request_item, "muhick_cost_code")
	return None


def refresh_budgets(doc, method=None):
	projects = {doc.project} if doc.project else set()
	for row in doc.items:
		projects.add(row.project)
		projects.add(_warehouse(row.t_warehouse).project)
	budget_engine.refresh_projects(projects)


# ------------------------------------------------------------------ quarantine
def _block_quarantine(doc, moves):
	"""Quarantine stock cannot be issued or delivered until released."""
	settings = get_settings()
	if not settings.block_issue_from_quarantine:
		return
	role = settings.quarantine_release_role
	if role and user_has_any_role(role, "System Manager"):
		return
	for source, _target in moves:
		if source and _warehouse(source).store_type == "Quarantine":
			frappe.throw(
				_("{0} is a quarantine store. Stock there must be inspected and released by {1} before it is used.").format(
					source, role or _("an authorised role")
				),
				title=_("Quarantine Stock"),
			)


def validate_delivery_note(doc, method=None):
	_block_quarantine(doc, [(row.warehouse, None) for row in doc.items])


# ------------------------------------------------------------------ Warehouse
def validate_warehouse(doc, method=None):
	store_type = doc.get("muhick_store_type")
	if store_type in SITE_TYPES and not doc.get("muhick_project") and not doc.is_group:
		frappe.throw(_("Select the project this site store belongs to."))
	if store_type not in SITE_TYPES:
		doc.muhick_project = None
	if not doc.get("muhick_stock_ownership"):
		if store_type == "Central Store":
			doc.muhick_stock_ownership = "Company"
		elif store_type in SITE_TYPES:
			doc.muhick_stock_ownership = "Project"
