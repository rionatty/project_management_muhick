// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Plan", {
	setup(frm) {
		frm.set_query("paid_from", "lines", () => ({
			filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			const fetch = (label, method) => {
				frm.add_custom_button(label, () => {
					if (!frm.doc.company) {
						frappe.msgprint(__("Select the company first."));
						return;
					}
					frm.call(method).then(() => {
						frm.refresh_fields();
						frm.dirty();
					});
				}, __("Get"));
			};
			fetch(__("Cash and Bank Balances"), "get_balances");
			fetch(__("Invoices Due"), "get_due_invoices");
			fetch(__("Payment Requests"), "get_payment_requests");
			fetch(__("Requisitions, Labour and Expense Claims"), "get_project_payables");
		}
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved") {
			frm.add_custom_button(__("Raise Payments"), () => raise_payments(frm)).addClass("btn-primary");
			frm.add_custom_button(__("Refresh Lines"), () => muhick.run(frm, "refresh_lines"));
		}
	},
});

frappe.ui.form.on("Payment Plan Line", {
	proposed_amount(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "approved_amount", locals[cdt][cdn].proposed_amount);
	},
});

// one draft Payment Entry per approved line that is paid with a payment entry
async function raise_payments(frm) {
	const types = ["Purchase Invoice", "Purchase Order", "Payment Request"];
	const lines = (frm.doc.lines || []).filter(
		(l) => l.line_status === "Approved" && !l.payment_entry && types.includes(l.reference_doctype)
	);
	if (!lines.length) {
		frappe.msgprint(__("Every approved line already has a payment, or is paid from its own form."));
		return;
	}
	const created = [];
	for (const line of lines) {
		const r = await frm.call("make_payment", { line: line.name });
		if (r && r.message) {
			created.push(r.message);
		}
	}
	await frm.reload_doc();
	frappe.msgprint(
		__("{0} draft payment(s) created: {1}. Complete the bank details and submit each one.", [
			created.length,
			created.join(", "),
		])
	);
}
