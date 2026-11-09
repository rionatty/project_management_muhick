// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Request for Quotation", {
	refresh(frm) {
		// the supplier for each line is chosen on the evaluation, from the quotations side by side
		if (frm.doc.docstatus === 1 && frappe.model.can_create("Supplier Evaluation")) {
			frm.add_custom_button(
				__("Supplier Evaluation"),
				() =>
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_procurement.doctype.supplier_evaluation.supplier_evaluation.make_supplier_evaluation",
						frm,
					}),
				__("Create")
			);
		}
	},
});
