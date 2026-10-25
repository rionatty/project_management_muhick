// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bid Document", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Ready" || !frm.doc.due_date) {
			return;
		}
		// how long is left to get it ready
		const days = frappe.datetime.get_day_diff(frm.doc.due_date, frappe.datetime.get_today());
		if (days <= 3) {
			frm.set_intro(
				days < 0 ? __("This document was needed {0} day(s) ago.", [-days]) : __("This document is needed in {0} day(s).", [days]),
				days < 0 ? "red" : "orange"
			);
		}
	},
});
