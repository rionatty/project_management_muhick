# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A requisition can now cover several approved quotations, so its supplier, quotation, currency, request and order
move onto its lines and its total is in the company's currency. An order needs an approved requisition from now on."""

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields

HEADER = "Procurement Requisition"


def execute():
	setup_custom_fields()
	frappe.db.set_single_value("Muhick Settings", "require_procurement_requisition", "Block")
	# the old columns stay in the table after the fields have gone; a new site never had them
	if not frappe.db.has_column(HEADER, "supplier_quotation"):
		return
	for requisition in frappe.db.sql(
		"select name, supplier_quotation, material_request, purchase_order from `tabProcurement Requisition`", as_dict=True
	):
		quotation = (
			frappe.db.get_value("Supplier Quotation", requisition.supplier_quotation, ["supplier", "supplier_name", "currency", "conversion_rate"], as_dict=True)
			or frappe._dict()
		)
		rate = quotation.conversion_rate or 1
		frappe.db.sql(
			"""
			update `tabProcurement Requisition Item`
			set supplier = %(supplier)s, supplier_name = %(supplier_name)s, supplier_quotation = %(quotation)s,
				currency = %(currency)s, conversion_rate = %(rate)s, base_amount = ifnull(amount, 0) * %(rate)s,
				purchase_order = %(order)s,
				material_request = case when ifnull(material_request_item, '') != '' then %(request)s end
			where parent = %(name)s and parenttype = 'Procurement Requisition'
			""",
			{
				"name": requisition.name,
				"supplier": quotation.supplier,
				"supplier_name": quotation.supplier_name,
				"quotation": requisition.supplier_quotation,
				"currency": quotation.currency,
				"rate": rate,
				"order": requisition.purchase_order,
				"request": requisition.material_request,
			},
		)
		total = frappe.db.sql(
			"select sum(base_amount) from `tabProcurement Requisition Item` where parent = %s and parenttype = 'Procurement Requisition'",
			(requisition.name,),
		)
		frappe.db.set_value(
			HEADER,
			requisition.name,
			{"suppliers": quotation.supplier_name or quotation.supplier, "total_amount": (total[0][0] if total else 0) or 0},
			update_modified=False,
		)
