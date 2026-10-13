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
	},
});
