// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Requisition", {
	setup(frm) {
		// a requisition pays for costs; the securities are bank guarantees
		frm.set_query("expense_type", "items", () => ({ filters: { kind: "Cost" } }));
		muhick.setup_cash_requisition(frm);
	},

	// the lines and the date come from the opportunity's financial requirements
	opportunity(frm) {
		if (!frm.doc.opportunity || frm.doc.docstatus !== 0) {
			return;
		}
		frappe.xcall("project_management_muhick.overrides.crm.get_bid_costs", { opportunity: frm.doc.opportunity }).then((costs) => {
			if (!(frm.doc.items || []).some((row) => row.expense_type)) {
				frm.clear_table("items");
				costs.items.forEach((line) => frm.add_child("items", line));
				frm.refresh_field("items");
			}
			if (costs.required_by && !frm.doc.required_by) {
				frm.set_value("required_by", costs.required_by);
			}
			if (!costs.items.length) {
				frappe.show_alert({ message: costs.note, indicator: "orange" }, 15);
			}
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			muhick.cash_requisition_actions(frm);
		}
	},
});
