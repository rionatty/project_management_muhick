// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurement Requisition", {
	setup(frm) {
		frm.set_query("supplier_quotation", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("cost_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		if (flt(frm.doc.total_price_variance) > 0 && frm.doc.docstatus === 0) {
			frm.set_intro(
				__("Sourced prices are {0} above the project budget.", [format_currency(frm.doc.total_price_variance)]),
				"orange"
			);
		}
		if (frm.doc.docstatus === 1 && !frm.doc.purchase_order) {
			frm.add_custom_button(__("Purchase Order"), () => {
				frappe
					.call({
						method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_purchase_order",
						args: { source_name: frm.doc.name },
						freeze: true,
					})
					.then((r) => r.message && frappe.set_route("Form", "Purchase Order", r.message));
			}, __("Create"));
		}
	},
});

frappe.ui.form.on("Procurement Requisition Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});
