// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bid Security Request", {
	setup(frm) {
		frm.set_query("security_type", "securities", () => ({ filters: { kind: "Bid Security" } }));
		frm.set_query("expense_type", "expenses", () => ({ filters: { kind: "Bid Security Expense" } }));
		frm.set_query("bank_facility", () => ({
			filters: { company: frm.doc.company, disabled: 0, facility_type: ["in", ["Guarantees and Bonds", "Combined"]] },
		}));
	},

	// what the chosen facility has left, before the request is approved
	bank_facility(frm) {
		if (!frm.doc.bank_facility) {
			frm.set_value("facility_available", 0);
			return;
		}
		frappe
			.xcall("project_management_muhick.muhick_sales.doctype.bid_security_request.bid_security_request.get_facility_headroom", {
				bank_facility: frm.doc.bank_facility,
				request: frm.is_new() ? null : frm.doc.name,
			})
			.then((room) => {
				frm.set_value("facility_available", room.available);
				if (flt(frm.doc.amount) > room.available) {
					frappe.show_alert({ message: __("The securities do not fit in what this facility has left."), indicator: "orange" }, 10);
				}
			});
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		// its funds are issued from the weekly payment plan
		if (frm.doc.status === "Approved" && flt(frm.doc.funds_required) > 0) {
			muhick.show_payment_schedule && muhick.show_payment_schedule(frm);
		}
		// once its funds are issued, or right after approval when it needs none
		const ready = frm.doc.status === "Funds Issued" || (frm.doc.status === "Approved" && !flt(frm.doc.funds_required));
		if (ready && finance && (frm.doc.securities || []).some((r) => !r.bank_instrument)) {
			frm.add_custom_button(
				__("Bid Security Issued"),
				() =>
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_sales.doctype.bid_security_request.bid_security_request.make_bank_instrument",
						frm: frm,
					}),
				__("Create")
			);
		}
	},
});
