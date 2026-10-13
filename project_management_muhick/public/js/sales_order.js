// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		const project_sale = ["Project", "Additions"].includes(frm.doc.muhick_sale_type);
		if (frm.doc.docstatus === 1 && project_sale) {
			frm.add_custom_button(
				__("Project Handover"),
				() => {
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_projects.doctype.project_handover.project_handover.make_from_sales_order",
						frm: frm,
					});
				},
				__("Create")
			);
		}
	},
});
