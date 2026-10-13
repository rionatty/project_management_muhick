// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier Quotation", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Compare Quotations"), () => {
				frappe.set_route("query-report", "Supplier Quotation Comparison", { company: frm.doc.company });
			});
		}
		// the approved quotation is the selected supplier: the requisition is raised from it
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Procurement Requisition"),
				() => {
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_from_supplier_quotation",
						frm: frm,
					});
				},
				__("Create")
			);
		}
	},
});
