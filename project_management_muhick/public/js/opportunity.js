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
		if (frm.is_new()) {
			return;
		}
		replace_close_and_reopen(frm);
		if ((frm.doc.items || []).length) {
			frm.add_custom_button(
				__("Supplier Comparison"),
				() => frappe.set_route("query-report", "Bid Margin Comparison", { opportunity: frm.doc.name }),
				__("View")
			);
		}
		if (["Lost", "Closed"].includes(frm.doc.status)) {
			return;
		}
		const create = (label, method) => {
			frm.add_custom_button(label, () => frappe.model.open_mapped_doc({ method: method, frm: frm }), __("Create"));
		};
		create(__("Sales Requisition"), "project_management_muhick.overrides.crm.make_sales_requisition");
		if (frm.doc.muhick_bid_security_required && !frm.doc.muhick_bid_security) {
			// approved by the Finance Manager, after which Finance issues the funds for it
			create(__("Bid Security Request"), "project_management_muhick.overrides.crm.make_bid_security_request");
		}
		show_outcome(frm);
		const submitted = !["Qualified", "In Preparation"].includes(frm.doc.sales_stage);
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

// the outcome report on its way to approval or, once the bid is in, Won and Lost to raise one: the
// Head of Sales and then the General Manager approve it before the bid is marked won or lost
function show_outcome(frm) {
	if (frm.doc.muhick_bid_outcome || !frappe.model.can_read("Bid Outcome")) {
		return;
	}
	frappe.db.get_value("Bid Outcome", { opportunity: frm.doc.name, docstatus: 0 }, ["name", "outcome", "status"]).then((r) => {
		const report = r.message || {};
		if (report.name) {
			frm.set_intro(
				__("Outcome report {0} ({1}) is {2}.", [
					frappe.utils.get_form_link("Bid Outcome", report.name, true),
					__(report.outcome),
					__(report.status).toLowerCase(),
				]),
				"blue"
			);
		} else if (["Submitted", "Under Evaluation"].includes(frm.doc.sales_stage) && frappe.model.can_create("Bid Outcome")) {
			const raise = (outcome) =>
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.overrides.crm.make_bid_outcome",
					frm: frm,
					args: { outcome: outcome },
				});
			frm.add_custom_button(__("Won"), () => raise("Won"), __("Outcome"));
			frm.add_custom_button(__("Lost"), () => raise("Lost"), __("Outcome"));
		}
	});
}

// ERPNext adds Close and Reopen after this script has run. A bid is closed with the reason; one whose
// outcome was approved is reopened only by cancelling its outcome report
function replace_close_and_reopen(frm) {
	setTimeout(() => {
		frm.remove_custom_button(__("Close"));
		frm.remove_custom_button(__("Reopen"));
		if (!frm.perm[0].write || frm.doc.muhick_bid_outcome || frm.doc.sales_stage === "Outcome Pending Approval") {
			return;
		}
		if (frm.doc.status === "Open") {
			frm.add_custom_button(__("Close"), () =>
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Why is the bid being closed?"), reqd: 1 },
					(values) => frm.set_value({ status: "Closed", muhick_outcome_notes: values.reason }).then(() => frm.save()),
					__("Close the Bid")
				)
			);
		} else if (frm.doc.status === "Closed") {
			frm.add_custom_button(__("Reopen"), () => frm.set_value("status", "Open").then(() => frm.save()));
		}
	});
}
