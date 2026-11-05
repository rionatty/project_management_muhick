// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Purchase Receipt", {
	setup(frm) {
		// raised from an order, it is on one of that order's consignments
		frm.set_query("muhick_import_shipment", () => {
			const orders = [...new Set((frm.doc.items || []).map((row) => row.purchase_order).filter(Boolean))];
			return { filters: orders.length ? { purchase_order: ["in", orders] } : {} };
		});
	},
});
