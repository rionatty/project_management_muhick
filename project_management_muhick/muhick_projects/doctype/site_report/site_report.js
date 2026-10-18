// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Site Report", {
	setup(frm) {
		frm.set_query("phase", "phases", () => muhick.phase_filters(frm.doc.project));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fetch from System"), () => {
				if (!(frm.doc.project && frm.doc.period_from && frm.doc.period_to)) {
					frappe.msgprint(__("Select the project and the period first."));
					return;
				}
				// fills phase progress, labour by trade, materials issued and equipment on site
				frm.call("fetch_from_system").then(() => {
					frm.refresh_fields();
					frm.dirty();
				});
			}).addClass("btn-primary");
		}
	},

	report_type(frm) {
		if (frm.doc.period_from || !frm.doc.report_type) {
			return;
		}
		const today = frappe.datetime.get_today();
		const days = { Weekly: -6, Monthly: -29 }[frm.doc.report_type];
		if (days) {
			frm.set_value("period_from", frappe.datetime.add_days(today, days));
			frm.set_value("period_to", today);
		}
	},
});

frappe.ui.form.on("Site Report Phase", {
	actual_percent(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "variance_percent", flt(row.actual_percent) - flt(row.planned_percent));
	},
});
