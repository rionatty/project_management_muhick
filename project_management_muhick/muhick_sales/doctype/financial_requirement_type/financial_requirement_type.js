// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Financial Requirement Type", {
	setup(frm) {
		frm.set_query("expense_account", () => ({ filters: { is_group: 0, root_type: "Expense" } }));
	},
});
