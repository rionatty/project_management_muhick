// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead", {
	refresh(frm) {
		// the organisation is what is mandatory; its contact person may not be known yet
		frm.set_df_property("first_name", "reqd", 0);
		// requirements are answered on the opportunity, while the technical bid is prepared
		const grid = frm.fields_dict.muhick_requirements && frm.fields_dict.muhick_requirements.grid;
		if (grid) {
			grid.toggle_display("compliance", false);
			grid.toggle_display("remarks", false);
		}
		if (frm.doc.qualification_status === "Qualified" && !["Opportunity", "Quotation", "Converted"].includes(frm.doc.status)) {
			frm.set_intro(__("Qualified. The next step is Create > Opportunity."), "blue");
		}
		// a lead is already one organisation, so prospects are not used; ERPNext adds these buttons
		// after this script has run
		setTimeout(() => {
			frm.remove_custom_button("Prospect", "Create");
			frm.remove_custom_button("Add to Prospect", "Action");
		});
	},

	company_name(frm) {
		show_known_organisation(frm);
	},
});

// the first step of the sales process: is this a new lead, or an organisation already known?
function show_known_organisation(frm) {
	const name = (frm.doc.company_name || "").trim();
	if (!name) {
		return;
	}
	Promise.all([
		frappe.db.get_list("Lead", { filters: { company_name: name, name: ["!=", frm.doc.name || ""] }, limit: 5 }),
		frappe.db.get_list("Customer", { filters: { customer_name: name }, limit: 5 }),
	]).then(([leads, customers]) => {
		const links = [
			...leads.map((l) => frappe.utils.get_form_link("Lead", l.name, true)),
			...customers.map((c) => frappe.utils.get_form_link("Customer", c.name, true)),
		];
		if (links.length) {
			frappe.show_alert({ message: __("{0} is already known: {1}", [frappe.utils.escape_html(name), links.join(", ")]), indicator: "orange" }, 15);
		}
	});
}
