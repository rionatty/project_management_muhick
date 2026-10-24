// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead", {
	refresh(frm) {
		// the organisation is what is mandatory; its contact person may not be known yet
		frm.set_df_property("first_name", "reqd", 0);
		if (!frm.is_new() && frm.doc.qualification_status !== "Not Pursued") {
			frm.add_custom_button(__("Bid"), () => make_bid(frm), __("Create"));
		}
	},
});

// a bid for the lead, with what the lead already says
function make_bid(frm) {
	const d = frm.doc;
	const values = {
		lead: d.name,
		title: (d.muhick_requirement || "").split("\n")[0].slice(0, 140),
		procuring_entity: d.company_name || d.lead_name,
		customer: d.customer,
		assigned_to: d.lead_owner,
		company: d.company,
		lead_source: d.utm_source,
		bid_type: d.request_type,
		status: d.qualification_status === "Qualified" ? "Qualified" : "Identified",
		submission_deadline: d.muhick_submission_deadline,
		site_visit_required: d.muhick_site_visit_required,
		site_visit_date: d.muhick_site_visit_date,
		financial_requirement: d.muhick_financial_requirement,
		qualification_notes: d.muhick_qualification_notes,
	};
	for (const key in values) {
		if (!values[key]) {
			delete values[key];
		}
	}
	frappe.new_doc("Bid", values);
}
