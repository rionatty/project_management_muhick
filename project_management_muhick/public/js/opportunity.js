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
		if (frm.is_new() || ["Lost", "Closed"].includes(frm.doc.status)) {
			return;
		}
		// the next steps of the sales process: the sales requisition goes on the bid, started if needed
		frm.add_custom_button(
			__("Sales Requisition"),
			() =>
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_sales.doctype.bid.bid.make_sales_requisition_for_opportunity",
					frm: frm,
				}),
			__("Create")
		);
		frm.add_custom_button(
			__("Bid"),
			() => frappe.model.open_mapped_doc({ method: "project_management_muhick.muhick_sales.doctype.bid.bid.make_bid", frm: frm }),
			__("Create")
		);
	},
});
