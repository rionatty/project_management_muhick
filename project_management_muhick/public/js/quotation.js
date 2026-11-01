// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frappe.model.can_email(null, frm)) {
			frm.add_custom_button(__("Email to Client"), () => frm.email_doc());
		}
		if (!frm.is_new() && frm.doc.docstatus === 0 && !(frm.doc.taxes || []).length) {
			frm.set_intro(__("This quotation has no VAT line."), "orange");
		}
	},
});
