// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		// "Sales" stays only as ERPNext's fallback; the types of work are the business's own
		frm.set_query("opportunity_type", () => ({ filters: { name: ["!=", "Sales"] } }));
	},

	onload(frm) {
		if (!frm.is_new()) {
			return;
		}
		// instead of ERPNext's "Sales", the type of work comes from the lead or is chosen
		if (frm.doc.opportunity_type === undefined) {
			frm.doc.opportunity_type = "";
		}
		if (frm.doc.opportunity_from === "Lead" && frm.doc.party_name && !frm.doc.opportunity_type) {
			frappe.db.get_value("Lead", frm.doc.party_name, "request_type").then((r) => {
				if (r.message && r.message.request_type) {
					frm.set_value("opportunity_type", r.message.request_type);
				}
			});
		}
	},

	refresh(frm) {
		if (!frm.is_new() && !["Lost", "Closed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Bid"), () => make_bid(frm), __("Create"));
		}
	},
});

// the opportunity's bid (requisition, documents, submission, follow-ups and outcome), started with
// what the opportunity and its lead already say
function make_bid(frm) {
	const stages = ["Qualified", "In Preparation", "Submitted", "Under Evaluation"];
	const d = frm.doc;
	const from_lead = d.opportunity_from === "Lead";
	const facts = from_lead
		? frappe.db
				.get_value("Lead", d.party_name, [
					"muhick_submission_deadline",
					"muhick_site_visit_required",
					"muhick_site_visit_date",
					"muhick_financial_requirement",
					"muhick_qualification_notes",
				])
				.then((r) => r.message || {})
		: Promise.resolve({});
	facts.then((lead) => {
		const values = {
			opportunity: d.name,
			lead: from_lead ? d.party_name : null,
			customer: d.opportunity_from === "Customer" ? d.party_name : null,
			title: (d.muhick_requirement || "").split("\n")[0].slice(0, 140),
			procuring_entity: d.customer_name,
			assigned_to: d.opportunity_owner,
			company: d.company,
			lead_source: d.utm_source,
			bid_type: d.opportunity_type === "Sales" ? null : d.opportunity_type,
			status: stages.includes(d.sales_stage) ? d.sales_stage : "Qualified",
			submission_deadline: lead.muhick_submission_deadline,
			site_visit_required: lead.muhick_site_visit_required,
			site_visit_date: lead.muhick_site_visit_date,
			financial_requirement: lead.muhick_financial_requirement,
			qualification_notes: lead.muhick_qualification_notes,
		};
		for (const key in values) {
			if (!values[key]) {
				delete values[key];
			}
		}
		frappe.new_doc("Bid", values);
	});
}
