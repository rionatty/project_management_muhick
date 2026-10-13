// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Equipment Allocation", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		if (["Allocated", "Under Repair"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Transfer to Another Project"), () => {
				frappe.prompt(
					[
						{ fieldname: "to_project", fieldtype: "Link", options: "Project", label: __("To Project"), reqd: 1 },
						{ fieldname: "responsible_person", fieldtype: "Link", options: "User", label: __("Responsible Person"), reqd: 1 },
					],
					(values) => {
						frm.call("transfer", values).then((r) => {
							if (r.message) {
								frappe.set_route("Form", "Project Equipment Allocation", r.message);
							}
						});
					},
					__("Hand Over Equipment")
				);
			});
		}
		if (frm.doc.from_allocation && !frm.doc.handover_accepted_by) {
			frm.set_intro(__("This equipment was handed over from project {0}. Confirm you have received it.", [frm.doc.from_project]), "orange");
			frm.add_custom_button(__("Accept Handover"), () => muhick.run(frm, "accept_handover")).addClass("btn-primary");
		}
	},
});
