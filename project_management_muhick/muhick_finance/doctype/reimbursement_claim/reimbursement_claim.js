// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reimbursement Claim", {
	setup(frm) {
		frm.set_query("cost_code", "expenses", () => ({ filters: { disabled: 0 } }));
		frm.set_query("expense_account", "expenses", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: "Expense" },
		}));
	},

	refresh(frm) {
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved" && finance) {
			frm.add_custom_button(__("Refund the Claimant"), () => {
				frappe.prompt(
					[
						{
							fieldname: "paid_from_account",
							fieldtype: "Link",
							options: "Account",
							label: __("Pay From (Cash or Bank)"),
							reqd: 1,
							get_query: () => ({
								filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
							}),
						},
						{ fieldname: "posting_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
					],
					(values) => {
						frm.call("make_journal_entry", values).then((r) => {
							if (r.message) {
								frappe.set_route("Form", "Journal Entry", r.message);
							}
						});
					},
					__("Refund by Journal Entry")
				);
			}).addClass("btn-primary");
		}
	},
});
