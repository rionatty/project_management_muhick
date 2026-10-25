// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		// "Sales" stays only as ERPNext's fallback; the types of work are the business's own
		frm.set_query("opportunity_type", () => ({ filters: { name: ["!=", "Sales"] } }));
		// from a qualified lead or an existing customer, not from a prospect
		frm.set_query("opportunity_from", () => ({ filters: { name: ["in", ["Lead", "Customer"]] } }));
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
		toggle_bid_price(frm);
		if (frm.is_new() || ["Lost", "Closed"].includes(frm.doc.status)) {
			return;
		}
		const create = (label, method) => {
			frm.add_custom_button(label, () => frappe.model.open_mapped_doc({ method: method, frm: frm }), __("Create"));
		};
		create(__("Sales Requisition"), "project_management_muhick.overrides.crm.make_sales_requisition");
		if (frm.doc.muhick_bid_security_required && !frm.doc.muhick_bid_security) {
			create(__("Bid Security"), "project_management_muhick.overrides.crm.make_bid_security");
		}
		const submitted = ["Submitted", "Under Evaluation", "Awarded"].includes(frm.doc.sales_stage);
		if (frm.doc.muhick_submission_deadline && !submitted) {
			const days = frappe.datetime.get_day_diff(frm.doc.muhick_submission_deadline, frappe.datetime.now_datetime());
			if (days <= 3) {
				frm.set_intro(__("Submission is due in {0} day(s).", [Math.max(days, 0)]), days < 0 ? "red" : "orange");
			}
		}
	},
});

frappe.ui.form.on("Opportunity Item", {
	items_add: toggle_bid_price,
	items_remove: toggle_bid_price,
});

// with BOQ lines, the bid price is their total
function toggle_bid_price(frm) {
	frm.toggle_enable("opportunity_amount", !(frm.doc.items || []).length);
}
