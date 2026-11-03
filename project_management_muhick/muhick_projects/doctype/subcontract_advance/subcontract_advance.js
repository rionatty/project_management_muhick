// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Subcontract Advance", {
	setup(frm) {
		frm.set_query("subcontract_agreement", () => ({ filters: { docstatus: 1, status: "Active", advance_amount: [">", 0] } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			muhick.show_payment_schedule(frm);
		}
	},

	// what the agreement's payment terms still allow
	subcontract_agreement(frm) {
		if (!frm.doc.subcontract_agreement || flt(frm.doc.amount) || frm.doc.docstatus !== 0) {
			return;
		}
		frappe
			.xcall("project_management_muhick.muhick_projects.doctype.subcontract_advance.subcontract_advance.get_advance_left", {
				agreement: frm.doc.subcontract_agreement,
			})
			.then((left) => {
				if (flt(left) > 0) {
					frm.set_value("amount", left);
				}
			});
	},
});
