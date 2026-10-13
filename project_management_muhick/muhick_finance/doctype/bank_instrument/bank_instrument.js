// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Instrument", {
	setup(frm) {
		frm.set_query("bank_facility", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		if (frm.doc.status === "Cancellation Requested") {
			frm.set_intro(__("Cancellation has been requested. The bank keeps charging until it is cancelled: set the status to Cancelled once the bank confirms."), "orange");
		}
	},
});
