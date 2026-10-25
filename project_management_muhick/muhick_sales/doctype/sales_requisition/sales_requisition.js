// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Requisition", {
	setup(frm) {
		// a requisition pays for costs; the securities are bank guarantees
		frm.set_query("expense_type", "items", () => ({ filters: { kind: "Cost" } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const status = frm.doc.status;
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (status === "Approved" && finance) {
			frm.add_custom_button(__("Record Payment"), () => {
				muhick.prompt_and_run(
					frm,
					__("Money Issued"),
					[
						{ fieldname: "amount_issued", fieldtype: "Currency", label: __("Amount Issued"), reqd: 1, default: frm.doc.total_amount },
						{ fieldname: "issued_on", fieldtype: "Date", label: __("Issued On"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "payment_reference", fieldtype: "Data", label: __("Payment Reference") },
					],
					"mark_paid"
				);
			}).addClass("btn-primary");
		}
		if (status === "Paid") {
			frm.set_intro(__("Record the expenses with receipts in the Accountability section, save, then submit the accountability."), "blue");
			frm.add_custom_button(__("Submit Accountability"), () => {
				const submit = () => muhick.run(frm, "submit_accountability");
				frm.is_dirty() ? frm.save("Update").then(submit) : submit();
			}).addClass("btn-primary");
		}
		if (status === "Accountability Submitted" && finance) {
			frm.add_custom_button(__("Verify Accountability"), () => muhick.run(frm, "verify_accountability")).addClass("btn-primary");
		}
		if (status === "Accounted" && finance) {
			const returning = flt(frm.doc.balance_to_return) > 0;
			const due = returning ? flt(frm.doc.balance_to_return) - flt(frm.doc.returned_amount) : flt(frm.doc.reimbursement_due);
			frm.add_custom_button(returning ? __("Record Balance Returned") : __("Record Reimbursement Paid"), () => {
				muhick.prompt_and_run(
					frm,
					returning ? __("Balance Returned") : __("Reimbursement Paid"),
					[
						{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1, default: due },
						{ fieldname: "reference", fieldtype: "Data", label: __("Reference") },
					],
					"settle"
				);
			}).addClass("btn-primary");
		}
	},
});
