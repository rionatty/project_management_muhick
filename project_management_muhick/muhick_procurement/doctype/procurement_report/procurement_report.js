// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurement Report", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		// the requisition is raised from here, for the items with a supplier chosen and not yet on one
		if ((frm.doc.items || []).some((row) => row.status === "Supplier Selected") && frappe.model.can_create("Procurement Requisition")) {
			frm.add_custom_button(
				__("Procurement Requisition"),
				() =>
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_from_procurement_report",
						frm,
					}),
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}
	},
});
