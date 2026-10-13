// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Labour Schedule", {
	setup(frm) {
		muhick.set_project_queries(frm);
	},
});

frappe.ui.form.on("Labour Schedule Line", {
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
	headcount: (frm, cdt, cdn) => set_labour_amount(cdt, cdn),
	days: (frm, cdt, cdn) => set_labour_amount(cdt, cdn),
	daily_rate: (frm, cdt, cdn) => set_labour_amount(cdt, cdn),
});

function set_labour_amount(cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.headcount) * flt(row.days) * flt(row.daily_rate));
}
