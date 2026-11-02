// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Plan", {
	setup(frm) {
		const paying_accounts = () => ({
			filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
		});
		frm.set_query("pay_from", paying_accounts);
		frm.set_query("paid_from", "lines", paying_accounts);
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.period_from && !frm.doc.period_to) {
			set_period(frm);
		}
	},

	plan_type(frm) {
		if (frm.is_new()) {
			set_period(frm);
		}
	},

	// the lines that were following the plan's account go on following it; a line given its own keeps it
	pay_from(frm) {
		(frm.doc.lines || []).forEach((line) => {
			if (!line.paid_from || line.paid_from === frm.pay_from_was) {
				frappe.model.set_value(line.doctype, line.name, "paid_from", frm.doc.pay_from);
			}
		});
		frm.pay_from_was = frm.doc.pay_from;
		show_allocation(frm);
	},

	refresh(frm) {
		frm.pay_from_was = frm.doc.pay_from;
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
			fetch(__("Approved Requisitions"), "get_approved_requisitions");
			fetch(__("Requisitions, Labour and Expense Claims"), "get_project_payables");
			fetch(__("Bank Fees Due"), "get_bank_fees");
		}
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved") {
			frm.add_custom_button(__("Raise Payments"), () => raise_payments(frm)).addClass("btn-primary");
			frm.add_custom_button(__("Refresh Lines"), () => muhick.run(frm, "refresh_lines"));
			const issuable = (frm.doc.lines || []).filter(
				(l) => l.line_status === "Approved" && ["Sales Requisition", "Bid Security Request", "Bank Instrument"].includes(l.reference_doctype)
			);
			if (issuable.length) {
				frm.add_custom_button(__("Issue Funds"), () => issue_funds(frm, issuable));
			}
		}
	},
});

frappe.ui.form.on("Payment Plan Line", {
	proposed_amount(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "approved_amount", locals[cdt][cdn].proposed_amount);
	},
	approved_amount: show_allocation,
	paid_from: show_allocation,
	line_status: show_allocation,
	lines_remove: show_allocation,
});

// the current week or month, which the dates can then be changed from
function set_period(frm) {
	const monthly = frm.doc.plan_type === "Monthly";
	frm.set_value("period_from", (monthly ? frappe.datetime.month_start() : frappe.datetime.week_start()).slice(0, 10));
	frm.set_value("period_to", (monthly ? frappe.datetime.month_end() : frappe.datetime.week_end()).slice(0, 10));
}

// what each account pays out under the plan, as the lines are allocated
function show_allocation(frm) {
	const allocated = {};
	(frm.doc.lines || []).forEach((line) => {
		if (line.paid_from && !["Held", "Not Executed"].includes(line.line_status)) {
			allocated[line.paid_from] = (allocated[line.paid_from] || 0) + flt(line.approved_amount);
		}
	});
	(frm.doc.accounts || []).forEach((account) => {
		account.allocated = allocated[account.account] || 0;
		account.balance_after = flt(account.balance) - account.allocated;
	});
	frm.refresh_field("accounts");
}

// pay one sales requisition, bid security request or bank fee line: the document records the funds issued
function issue_funds(frm, lines) {
	const dialog = frappe.prompt(
		[
			{
				fieldname: "line",
				fieldtype: "Select",
				label: __("Line"),
				reqd: 1,
				default: lines[0].name,
				options: lines.map((l) => ({
					value: l.name,
					label: `${l.reference_name}: ${l.party || ""} ${format_currency(l.approved_amount, frm.doc.currency)}`,
				})),
				onchange() {
					const chosen = lines.find((l) => l.name === this.get_value());
					if (chosen && chosen.paid_from) {
						dialog.set_value("paid_from", chosen.paid_from);
					}
				},
			},
			{
				fieldname: "paid_from",
				fieldtype: "Link",
				label: __("Pay From Account"),
				options: "Account",
				reqd: 1,
				default: lines[0].paid_from,
				get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] } }),
			},
			{ fieldname: "issued_on", fieldtype: "Date", label: __("Issued On"), reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: "payment_reference", fieldtype: "Data", label: __("Payment Reference") },
			{
				fieldname: "accountability_due_date",
				fieldtype: "Date",
				label: __("Account By"),
			},
		],
		(values) => muhick.run(frm, "issue_funds", values),
		__("Issue Funds")
	);
}

// one draft Payment Entry per approved line that is paid with a payment entry
async function raise_payments(frm) {
	const types = ["Purchase Invoice", "Purchase Order", "Payment Request", "Procurement Requisition"];
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
		__("{0} draft payment(s) created: {1}. Enter the bank's reference and submit each one.", [
			created.length,
			created.join(", "),
		])
	);
}
