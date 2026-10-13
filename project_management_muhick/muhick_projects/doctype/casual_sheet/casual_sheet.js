// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Casual Sheet", {
	setup(frm) {
		muhick.set_project_queries(frm);
	},

	refresh(frm) {
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved" && finance) {
			frm.add_custom_button(__("Record Payment"), () => {
				muhick.prompt_and_run(
					frm,
					__("Wages Paid"),
					[
						{ fieldname: "paid_on", fieldtype: "Date", label: __("Paid On"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "payment_reference", fieldtype: "Data", label: __("Payment Reference") },
					],
					"mark_paid"
				);
			}).addClass("btn-primary");
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
