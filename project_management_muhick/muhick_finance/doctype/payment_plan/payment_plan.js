// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Plan", {
	setup(frm) {
		const paying_accounts = () => ({
			filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
		});
		frm.set_query("pay_from", paying_accounts);
		// an account in another currency pays only what is owed in that currency
		frm.set_query("paid_from", "lines", (doc, cdt, cdn) => {
			const query = paying_accounts();
			const owed = locals[cdt][cdn].currency;
			if (owed) {
				query.filters.account_currency = ["in", [erpnext.get_currency(frm.doc.company), owed]];
			}
			return query;
		});
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

	// the lines that were following the plan's account go on following it, where it can pay them; a line given its own keeps it
	async pay_from(frm) {
		const home = erpnext.get_currency(frm.doc.company);
		const account = frm.doc.pay_from ? await frappe.db.get_value("Account", frm.doc.pay_from, "account_currency") : null;
		const held_in = account && account.message.account_currency;
		(frm.doc.lines || []).forEach((line) => {
			if (!line.paid_from || line.paid_from === frm.pay_from_was) {
				const fits = !held_in || held_in === home || held_in === line.currency;
				frappe.model.set_value(line.doctype, line.name, "paid_from", fits ? frm.doc.pay_from : null);
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
						show_allocation(frm);
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

// what each account pays out under the plan as the lines are allocated, in the account's own currency
function show_allocation(frm) {
	const home = erpnext.get_currency(frm.doc.company);
	(frm.doc.accounts || []).forEach((account) => {
		const foreign = account.currency && account.currency !== home;
		account.allocated = (frm.doc.lines || [])
			.filter((line) => line.paid_from === account.account && !["Held", "Not Executed"].includes(line.line_status))
			.reduce((sum, line) => sum + flt(line.approved_amount) / (foreign ? flt(line.exchange_rate) || 1 : 1), 0);
		account.balance_after = flt(account.balance) - account.allocated;
	});
	frm.refresh_field("accounts");
}

// one draft payment per approved line paid from the plan; what happened to each is said once
async function raise_payments(frm) {
	const { created, waiting, closed, failed } = (await frm.call("raise_payments")).message;
	await frm.reload_doc();
	const links = (payments) => payments.map((p) => frappe.utils.get_form_link(p.doctype, p.name, true)).join(", ");
	const parts = [];
	if (created.length) {
		parts.push(__("{0} draft payment(s) created: {1}. Enter the bank's reference and submit each one.", [created.length, links(created)]));
	}
	if (waiting.length) {
		parts.push(__("Raised before and waiting to be submitted: {0}.", [links(waiting)]));
	}
	if (closed.length) {
		parts.push(__("Nothing is left to pay on {0}, so the line is closed as Not Executed.", [closed.join(", ")]));
	}
	if (failed.length) {
		parts.push(__("Not raised:") + "<br>" + failed.map((f) => __("Row {0}, {1}: {2}", [f.row, f.document, f.reason])).join("<br>"));
	}
	frappe.msgprint({
		title: __("Raise Payments"),
		indicator: failed.length ? "orange" : "green",
		message: parts.join("<br><br>") || __("No approved line is waiting to be paid from here."),
	});
}
