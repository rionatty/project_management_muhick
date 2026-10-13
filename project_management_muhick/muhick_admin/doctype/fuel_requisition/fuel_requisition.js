// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fuel Requisition", {
	litres: (frm) => frm.set_value("amount", flt(frm.doc.litres) * flt(frm.doc.rate)),
	rate: (frm) => frm.set_value("amount", flt(frm.doc.litres) * flt(frm.doc.rate)),
});
