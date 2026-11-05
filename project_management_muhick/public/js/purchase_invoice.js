// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Purchase Invoice", {
	setup(frm) {
		// raised from an order, it is on one of that order's consignments
		frm.set_query("muhick_import_shipment", () => {
			const orders = [...new Set((frm.doc.items || []).map((row) => row.purchase_order).filter(Boolean))];
			return { filters: orders.length ? { purchase_order: ["in", orders] } : {} };
		});
		frm.set_query("muhick_service_receipt_note", () => ({
			filters: {
				subcontract_agreement: frm.doc.muhick_subcontract_agreement || "",
				docstatus: 1,
			},
		}));
	},

	refresh(frm) {
		if (frm.doc.muhick_match_status === "Awaiting Goods") {
			frm.set_intro(__("Reserve invoice: the goods have not arrived yet."), "blue");
		}
		if (frm.is_new() || frm.doc.muhick_match_status !== "Exception") {
			return;
		}
		const remarks = frappe.utils.escape_html(frm.doc.muhick_match_remarks || "").replace(/\n/g, "<br>");
		frm.set_intro(`${__("Three-way match exception")}:<br>${remarks}`, "red");
		frm.add_custom_button(__("Override Match Exception"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for Override"), reqd: 1 },
				(values) => {
					frappe
						.call({
							method: "project_management_muhick.muhick_controls.matching.override",
							args: { purchase_invoice: frm.doc.name, reason: values.reason },
							freeze: true,
						})
						.then(() => frm.reload_doc());
				},
				__("Override Three-Way Match")
			);
		});
	},
});
