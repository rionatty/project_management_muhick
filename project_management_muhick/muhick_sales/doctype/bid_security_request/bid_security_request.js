// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bid Security Request", {
	setup(frm) {
		frm.set_query("security_type", "securities", () => ({ filters: { kind: "Bid Security" } }));
		frm.set_query("expense_type", "expenses", () => ({ filters: { kind: "Bid Security Expense" } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (frm.doc.status === "Approved" && finance) {
			frm.add_custom_button(__("Record Funds Issued"), () => {
				muhick.prompt_and_run(
					frm,
					__("Funds Issued"),
					[
						{ fieldname: "amount_issued", fieldtype: "Currency", label: __("Amount Issued"), reqd: 1, default: frm.doc.funds_required },
						{ fieldname: "issued_on", fieldtype: "Date", label: __("Issued On"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "payment_reference", fieldtype: "Data", label: __("Payment Reference") },
					],
					"record_funds_issued"
				);
			}).addClass("btn-primary");
		}
		if (frm.doc.status === "Funds Issued" && finance && (frm.doc.securities || []).some((r) => !r.bank_instrument)) {
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
