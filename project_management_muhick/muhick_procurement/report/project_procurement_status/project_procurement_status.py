# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every item requested for a project: what was requisitioned, ordered, received and invoiced,
and what is still outstanding, so nobody has to chase the status of a requisition."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "material_request", "label": _("Material Request"), "fieldtype": "Link", "options": "Material Request", "width": 160},
		{"fieldname": "transaction_date", "label": _("Requested On"), "fieldtype": "Date", "width": 105},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "progress", "label": _("Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "requested_qty", "label": _("Requested"), "fieldtype": "Float", "width": 100},
		{"fieldname": "ordered_qty", "label": _("Ordered"), "fieldtype": "Float", "width": 100},
		{"fieldname": "received_qty", "label": _("Received"), "fieldtype": "Float", "width": 100},
		{"fieldname": "outstanding_qty", "label": _("Outstanding"), "fieldtype": "Float", "width": 100},
		{"fieldname": "purchase_orders", "label": _("Purchase Orders"), "fieldtype": "Data", "width": 180},
		{"fieldname": "ordered_amount", "label": _("Ordered Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "invoiced_amount", "label": _("Invoiced Amount"), "fieldtype": "Currency", "width": 140},
	]
	conditions, params = ["mr.docstatus < 2"], {}
	if filters.project:
		conditions.append("mri.project = %(project)s")
		params["project"] = filters.project
	if filters.from_date:
		conditions.append("mr.transaction_date >= %(from_date)s")
		params["from_date"] = filters.from_date
	if filters.to_date:
		conditions.append("mr.transaction_date <= %(to_date)s")
		params["to_date"] = filters.to_date
	rows = frappe.db.sql(
		f"""
		select mr.name as material_request, mr.transaction_date, mr.docstatus, mr.status as request_status,
			mr.material_request_type, mri.name as row_name, mri.project, mri.item_code, mri.item_name,
			mri.stock_qty as requested_qty, mri.ordered_qty, mri.received_qty
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where {" and ".join(conditions)}
		order by mr.transaction_date desc, mr.name, mri.idx
		limit 5000
		""",
		params,
		as_dict=True,
	)
	orders = _orders([r.row_name for r in rows])
	data = []
	for r in rows:
		order = orders.get(r.row_name) or frappe._dict()
		r.purchase_orders = order.get("purchase_orders")
		r.ordered_amount = flt(order.get("ordered_amount"))
		r.invoiced_amount = flt(order.get("invoiced_amount"))
		r.outstanding_qty = max(flt(r.requested_qty) - flt(r.received_qty), 0)
		r.progress = _progress(r)
		if filters.only_outstanding and r.progress in (_("Received"), _("Issued"), _("Stopped")):
			continue
		data.append(r)
	return columns, data


def _orders(material_request_rows) -> dict:
	if not material_request_rows:
		return {}
	rows = frappe.db.sql(
		"""
		select poi.material_request_item, group_concat(distinct po.name separator ', ') as purchase_orders,
			sum(poi.base_net_amount) as ordered_amount,
			sum(ifnull(poi.billed_amt, 0) * po.conversion_rate) as invoiced_amount
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and poi.material_request_item in %(rows)s
		group by poi.material_request_item
		""",
		{"rows": tuple(material_request_rows)},
		as_dict=True,
	)
	return {r.material_request_item: r for r in rows}


def _progress(row) -> str:
	if row.docstatus == 0:
		return _("Awaiting Approval")
	if row.request_status == "Stopped":
		return _("Stopped")
	if row.material_request_type != "Purchase":
		return _("Issued") if row.request_status in ("Issued", "Transferred", "Received") else _("Awaiting Issue")
	if flt(row.received_qty) >= flt(row.requested_qty) > 0:
		return _("Received")
	if flt(row.received_qty) > 0:
		return _("Partly Received")
	if flt(row.ordered_qty) >= flt(row.requested_qty) > 0:
		return _("Ordered")
	if flt(row.ordered_qty) > 0:
		return _("Partly Ordered")
	return _("Awaiting Order")
