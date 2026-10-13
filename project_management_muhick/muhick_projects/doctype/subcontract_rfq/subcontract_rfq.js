// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Subcontract RFQ", {
	setup(frm) {
		muhick.set_project_queries(frm);
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.subcontract_agreement) {
			frm.add_custom_button(__("Subcontract Agreement"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.subcontract_rfq.subcontract_rfq.make_subcontract_agreement",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});

frappe.ui.form.on("Subcontract RFQ Quotation", {
	// only one subcontractor can be selected
	is_selected(frm, cdt, cdn) {
		const picked = locals[cdt][cdn];
		if (!picked.is_selected) {
			return;
		}
		(frm.doc.quotations || []).forEach((row) => {
			if (row.name !== picked.name && row.is_selected) {
				frappe.model.set_value(row.doctype, row.name, "is_selected", 0);
			}
		});
	},
	quoted_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.quoted_amount) > 0 && !row.quotation_received) {
			frappe.model.set_value(cdt, cdn, "quotation_received", 1);
		}
	},
});
