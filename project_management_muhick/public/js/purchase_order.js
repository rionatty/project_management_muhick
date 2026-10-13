// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		// a delivery note for goods going on to site, raised from the approved order
		frm.add_custom_button(
			__("Delivery to Site"),
			() => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.overrides.buying.make_site_transfer",
					frm: frm,
				});
			},
			__("Create")
		);
		if (frm.doc.muhick_payment_type === "Advance" && flt(frm.doc.advance_paid) === 0) {
			frm.set_intro(
				__("The payment terms need an advance of {0}%. Raise the Payment Request from Create.", [
					flt(frm.doc.muhick_advance_percent),
				]),
				"blue"
			);
		}
		frm.add_custom_button(
			__("Consignment Tracking"),
			() => {
				frappe.new_doc("Import Shipment", {
					purchase_order: frm.doc.name,
					company: frm.doc.company,
					title: `${frm.doc.supplier_name || frm.doc.supplier} - ${frm.doc.name}`,
				});
			},
			__("Create")
		);
	},
});
