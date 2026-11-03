// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

const bank_accounts = (frm) => ({
	query: "project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.bank_account_query",
	filters: { company: frm.doc.company || "" },
});

frappe.ui.form.on("Resource Allocation", {
	setup(frm) {
		["from_project", "to_project"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { company: frm.doc.company || "", status: ["!=", "Cancelled"] } }));
		});
		["from_bank_account", "to_bank_account"].forEach((field) => {
			frm.set_query(field, () => bank_accounts(frm));
		});
	},

	refresh(frm) {
		show_funds(frm);
		if (frm.doc.docstatus !== 1) {
			return;
		}
		if (frm.doc.status === "Awaiting Transfer") {
			frm.set_intro(__("The money has still to move from {0} to {1}.", [frm.doc.from_bank_account, frm.doc.to_bank_account]), "orange");
		}
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (finance && transfers_due(frm)) {
			frm.add_custom_button(__("Internal Transfer"), () => raise_transfers(frm), __("Create"));
		}
		if (finance && flt(frm.doc.outstanding_amount) > 0.005 && frm.doc.status !== "Awaiting Transfer") {
			frm.add_custom_button(__("Record Refund"), () => record_refund(frm));
		}
		["from_project", "to_project"].forEach((field) => {
			frm.add_custom_button(
				__("Funds Statement: {0}", [frm.doc[field]]),
				() => frappe.set_route("query-report", "Project Funds Statement", { project: frm.doc[field] }),
				__("View")
			);
		});
	},

	from_project: show_funds,
	to_project: show_funds,
	company: show_funds,

	from_bank_account(frm) {
		if (frm.doc.from_bank_account && !frm.doc.to_bank_account) {
			frm.set_value("to_bank_account", frm.doc.from_bank_account);
		}
		bank_terms(frm);
	},
	to_bank_account: bank_terms,
	transfer_date: bank_terms,
	amount: set_amounts,
	exchange_rate: set_amounts,
});

// while it is prepared, what each project holds and in which bank
function show_funds(frm) {
	frm.set_intro("");
	const projects = [frm.doc.from_project, frm.doc.to_project].filter(Boolean);
	if (frm.doc.docstatus !== 0 || !frm.doc.company || !projects.length) {
		return;
	}
	frappe
		.xcall("project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.get_project_funds", {
			company: frm.doc.company,
			projects,
		})
		.then((funds) => {
			const currency = erpnext.get_currency(frm.doc.company);
			frm.set_intro(projects.map((project) => funds_line(funds[project], currency)).join("<br>"), "blue");
			// one bank holds all its money: that is the one
			const lender = funds[frm.doc.from_project];
			const holding = lender ? lender.banks.filter((bank) => flt(bank.amount) > 0) : [];
			if (!frm.doc.from_bank_account && holding.length === 1) {
				frm.set_value("from_bank_account", holding[0].account);
			}
		});
}

function funds_line(fund, currency) {
	const name = frappe.utils.escape_html(fund.name);
	const banks = fund.banks
		.map((bank) => `${frappe.utils.escape_html(bank.label)} ${format_currency(bank.amount, bank.currency)}`)
		.join(", ");
	if (flt(fund.available) < 0) {
		const short = __("{0} is short by {1}.", [name, format_currency(-flt(fund.available), currency)]);
		return banks ? `${short} ${banks}.` : short;
	}
	if (!fund.banks.length) {
		return __("{0} holds nothing in the bank.", [name]);
	}
	return __("{0} holds {1}: {2}.", [name, format_currency(fund.available, currency), banks]);
}

function bank_terms(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.company || !frm.doc.from_bank_account) {
		return;
	}
	frappe
		.xcall("project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.get_bank_terms", {
			company: frm.doc.company,
			from_bank_account: frm.doc.from_bank_account,
			to_bank_account: frm.doc.to_bank_account || frm.doc.from_bank_account,
			on_date: frm.doc.transfer_date,
		})
		.then((terms) => {
			frm
				.set_value({
					currency: terms.currency,
					to_currency: terms.to_currency,
					company_currency: terms.company_currency,
					exchange_rate: terms.exchange_rate,
				})
				.then(() => set_amounts(frm));
		});
}

// as the server works them out on saving: one rate, for the one currency that is not the company's
function converted(amount, currency, wanted, home, rate) {
	if (currency === wanted) {
		return flt(amount);
	}
	const base = currency === home ? flt(amount) : flt(amount) * flt(rate);
	return wanted === home ? base : base / flt(rate);
}

function set_amounts(frm) {
	const { amount, currency, to_currency, company_currency, exchange_rate } = frm.doc;
	if (!currency || !company_currency) {
		return;
	}
	const rate = flt(exchange_rate) || 1;
	frm.set_value("base_amount", converted(amount, currency, company_currency, company_currency, rate));
	frm.set_value("received_amount", converted(amount, currency, to_currency || currency, company_currency, rate));
}

function transfers_due(frm) {
	const due = (row) => row.from_bank_account !== row.to_bank_account && !row.transfer_entry;
	return due(frm.doc) || (frm.doc.refunds || []).some(due);
}

function raise_transfers(frm) {
	frm.call("raise_transfers").then(({ message }) => {
		frappe.show_alert({ message: __("Raised: {0}", [(message || []).join(", ")]), indicator: "green" });
		frm.reload_doc();
	});
}

function record_refund(frm) {
	let dialog = null;
	const bank_field = (fieldname, label, value) => ({
		fieldname,
		fieldtype: "Link",
		options: "Account",
		label,
		default: value,
		reqd: 1,
		get_query: () => bank_accounts(frm),
		onchange: () => dialog && refund_rate(frm, dialog),
	});
	dialog = frappe.prompt(
		[
			bank_field("from_bank_account", __("From Bank Account"), frm.doc.to_bank_account),
			bank_field("to_bank_account", __("To Bank Account"), frm.doc.from_bank_account),
			{
				fieldname: "amount",
				fieldtype: "Currency",
				options: "currency",
				label: __("Amount Refunded in {0}", [frm.doc.currency]),
				default: frm.doc.outstanding_amount,
				reqd: 1,
			},
			{ fieldname: "exchange_rate", fieldtype: "Float", label: __("Exchange Rate"), hidden: 1 },
			{ fieldname: "refund_date", fieldtype: "Date", label: __("Date"), default: frappe.datetime.get_today(), reqd: 1 },
			{ fieldname: "reference", fieldtype: "Data", label: __("Reference") },
		],
		(values) => frm.call("record_refund", values).then(() => frm.reload_doc()),
		__("Record Refund"),
		__("Record")
	);
	refund_rate(frm, dialog);
}

// a rate is asked for only where the money changes currency
function refund_rate(frm, dialog) {
	frappe
		.xcall("project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.get_bank_terms", {
			company: frm.doc.company,
			from_bank_account: dialog.get_value("from_bank_account"),
			to_bank_account: dialog.get_value("to_bank_account"),
			on_date: dialog.get_value("refund_date"),
			currency: frm.doc.currency,
		})
		.then((terms) => {
			dialog.set_df_property("exchange_rate", "hidden", terms.converts ? 0 : 1);
			dialog.set_value("exchange_rate", terms.converts ? terms.exchange_rate : 0);
		});
}
