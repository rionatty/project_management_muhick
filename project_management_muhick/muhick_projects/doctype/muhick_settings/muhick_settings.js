// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Muhick Settings", {
	setup(frm) {
		frm.set_query("site_store_parent_warehouse", () => ({ filters: { is_group: 1 } }));
		frm.set_query("document_type", "approval_thresholds", () => ({
			filters: {
				name: ["in", ["Procurement Requisition", "Purchase Order", "Project Requisition", "Fuel Requisition", "Vehicle Service Request"]],
			},
		}));
		["import_vat_account", "import_duty_account", "import_levy_account"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { is_group: 0 } }));
		});
		// what a payment to no supplier is charged to: not a bank, and not an account that needs a party
		["sales_requisition_account", "bid_security_account", "bank_charges_account"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { is_group: 0, account_type: ["not in", ["Bank", "Cash", "Receivable", "Payable"]] } }));
		});
		["central_store_warehouse", "goods_in_transit_warehouse"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { is_group: 0 } }));
		});
		["claim_income_item", "subcontract_service_item"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { is_stock_item: 0, disabled: 0 } }));
		});
	},
});
