// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bid", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.assigned_to) {
			frm.set_value("assigned_to", frappe.session.user);
		}
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		const open = !["Won", "Lost", "Cancelled", "Not Pursued"].includes(frm.doc.status);
		const create = (label, method) => {
			frm.add_custom_button(label, () => frappe.model.open_mapped_doc({ method: method, frm: frm }), __("Create"));
		};
		if (open) {
			create(__("Sales Requisition"), "project_management_muhick.muhick_sales.doctype.bid.bid.make_sales_requisition");
			if (frm.doc.bid_security_required && !frm.doc.bid_security) {
				create(__("Bid Security"), "project_management_muhick.muhick_sales.doctype.bid.bid.make_bid_security");
			}
		}
		if (open && frm.doc.submission_deadline) {
			const days = frappe.datetime.get_day_diff(frm.doc.submission_deadline, frappe.datetime.now_datetime());
			if (days <= 3) {
				frm.set_intro(__("Submission is due in {0} day(s).", [Math.max(days, 0)]), days < 0 ? "red" : "orange");
			}
		}
	},
});
