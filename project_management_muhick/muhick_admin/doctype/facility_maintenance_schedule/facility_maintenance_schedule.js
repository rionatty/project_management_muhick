// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Facility Maintenance Schedule", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Mark as Serviced"), () => {
				muhick.prompt_and_run(
					frm,
					__("Service Carried Out"),
					[{ fieldname: "done_on", fieldtype: "Date", label: __("Serviced On"), reqd: 1, default: frappe.datetime.get_today() }],
					"mark_done"
				);
			});
		}
	},
});
