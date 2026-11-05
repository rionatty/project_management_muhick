// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Import Shipment", {
	setup(frm) {
		frm.set_query("purchase_order", () => ({ filters: { docstatus: 1 } }));
	},

	refresh(frm) {
		if (frm.doc.is_delayed && !["Delivered", "Closed"].includes(frm.doc.shipment_status)) {
			frm.set_intro(__("This consignment is behind schedule."), "red");
		}
		if (frm.is_new()) {
			return;
		}
		// Finance books the reserve invoice from the supplier's commercial invoice
		if (frm.doc.commercial_invoice && frappe.model.can_create("Purchase Invoice")) {
			frm.add_custom_button(
				__("Reserve Invoice"),
				() => {
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_procurement.doctype.import_shipment.import_shipment.make_reserve_invoice",
						frm: frm,
					});
				},
				__("Create")
			);
		}
		if ((frm.doc.charges || []).length && frappe.model.can_create("Landed Cost Voucher")) {
			frm.add_custom_button(
				__("Landed Cost Voucher"),
				() => {
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_procurement.doctype.import_shipment.import_shipment.make_landed_cost_voucher",
						frm: frm,
					});
				},
				__("Create")
			);
		}
	},
});
