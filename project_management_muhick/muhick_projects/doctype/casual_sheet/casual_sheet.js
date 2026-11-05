// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Casual Sheet", {
	setup(frm) {
		muhick.set_project_queries(frm);
		frm.set_query("expense_account", () => ({
			query: "project_management_muhick.muhick_finance.cash_requisition.expense_account_query",
			filters: { company: frm.doc.company || "" },
		}));
	},

	refresh(frm) {
		// its wages are paid from the weekly payment plan
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved") {
			muhick.show_payment_schedule(frm);
		}
	},
});

frappe.ui.form.on("Casual Sheet Line", {
	trade(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.trade) {
			return;
		}
		frappe.db.get_value("Labour Trade", row.trade, "default_daily_rate").then((r) => {
			if (r.message && flt(r.message.default_daily_rate) && !flt(row.daily_rate)) {
				frappe.model.set_value(cdt, cdn, "daily_rate", r.message.default_daily_rate);
			}
		});
	},
	days_worked: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn, "days_worked", "daily_rate"),
	daily_rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn, "days_worked", "daily_rate"),
});
