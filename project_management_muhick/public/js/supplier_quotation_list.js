// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// several approved quotations go onto one requisition, each line keeping its own source
(() => {
	const settings = (frappe.listview_settings["Supplier Quotation"] = frappe.listview_settings["Supplier Quotation"] || {});
	const standard_onload = settings.onload;
	settings.onload = (listview) => {
		standard_onload && standard_onload(listview);
		if (frappe.model.can_create("Procurement Requisition")) {
			listview.page.add_action_item(__("Procurement Requisition"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_from_supplier_quotation",
					source_name: JSON.stringify(listview.get_checked_items(true)),
				});
			});
		}
	};
})();
