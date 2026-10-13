// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Requisition", {
	setup(frm) {
		muhick.set_project_queries(frm, ["items", "expenses"]);
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const status = frm.doc.status;
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		const reference = { fieldname: "reference", fieldtype: "Data", label: __("Reference") };

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
				// save the expense lines first so the server sees them
				const submit = () => muhick.run(frm, "submit_accountability");
				frm.is_dirty() ? frm.save("Update").then(submit) : submit();
			}).addClass("btn-primary");
		}
		if (status === "Accountability Submitted" && finance) {
			frm.add_custom_button(__("Verify Accountability"), () => {
				frappe.confirm(__("Have the expenses been checked against the supporting documents?"), () =>
					muhick.run(frm, "verify_accountability")
				);
			}).addClass("btn-primary");
		}
		if (status === "Accounted" && flt(frm.doc.balance_to_return) > 0 && finance) {
			const outstanding = flt(frm.doc.balance_to_return) - flt(frm.doc.returned_amount);
			frm.add_custom_button(__("Record Balance Returned"), () => {
				muhick.prompt_and_run(
					frm,
					__("Balance Returned by the Requester"),
					[{ fieldname: "amount", fieldtype: "Currency", label: __("Amount Returned"), reqd: 1, default: outstanding }, reference],
					"record_return"
				);
			}).addClass("btn-primary");
		}
		if (status === "Accounted" && flt(frm.doc.reimbursement_due) > 0) {
			if (!frm.doc.reimbursement_approved_by && frappe.user.has_role(["General Manager", "System Manager"])) {
				frm.add_custom_button(__("Approve Reimbursement"), () => muhick.run(frm, "approve_reimbursement")).addClass("btn-primary");
			}
			if (frm.doc.reimbursement_approved_by && finance) {
				frm.add_custom_button(__("Record Reimbursement Paid"), () => {
					muhick.prompt_and_run(frm, __("Reimbursement Paid"), [reference], "record_reimbursement");
				}).addClass("btn-primary");
			}
		}
	},
});

frappe.ui.form.on("Project Requisition Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});
