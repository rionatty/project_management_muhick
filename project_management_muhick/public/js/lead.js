// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead", {
	refresh(frm) {
		// the organisation is what is mandatory; its contact person may not be known yet
		frm.set_df_property("first_name", "reqd", 0);
		if (frm.doc.qualification_status === "Qualified" && !["Opportunity", "Quotation", "Converted"].includes(frm.doc.status)) {
			frm.set_intro(__("Qualified. The next step is Create > Opportunity."), "blue");
		}
	},
});
