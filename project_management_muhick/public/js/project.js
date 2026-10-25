// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		const stage = frm.doc.muhick_stage || "Planning";
		const project = { project: frm.doc.name };

		if (stage === "Planning") {
			frm.add_custom_button(__("Start Execution"), () => {
				frappe
					.call({
						method: "project_management_muhick.overrides.project.start_execution",
						args: project,
						freeze: true,
					})
					.then(() => frm.reload_doc());
			}).addClass("btn-primary");

			// show which activation gates are still open
			frappe.call({ method: "project_management_muhick.overrides.project.get_gates", args: project }).then((r) => {
				const gates = r.message || [];
				if (!gates.length) {
					return;
				}
				const lines = gates.map(
					(g) => `${g.met ? "&#10004;" : "&#10008;"} ${frappe.utils.escape_html(g.gate)}`
				);
				const all_met = gates.every((g) => g.met);
				frm.set_intro(
					`${__("Before execution can start:")}<br>${lines.join("<br>")}`,
					all_met ? "green" : "orange"
				);
			});
		}

		const create = (label, doctype, values) => {
			frm.add_custom_button(label, () => frappe.new_doc(doctype, values || project), __("Create"));
		};
		if (stage === "Planning") {
			// the BOQ starts from the sales order's lines and their stages
			frm.add_custom_button(
				__("Bill of Quantities"),
				() =>
					frappe.model.open_mapped_doc({
						method: "project_management_muhick.muhick_projects.doctype.project_boq.project_boq.make_from_project",
						frm: frm,
					}),
				__("Create")
			);
			create(__("Project Budget"), "Project Budget");
			create(__("Activity Plan"), "Project Activity Plan");
		}
		if (stage === "Execution" || stage === "Practical Completion") {
			create(__("Material Request"), "Material Request", {
				muhick_project: frm.doc.name,
				muhick_request_origin: stage === "Execution" ? "Project" : "Defects Liability",
			});
			create(__("Cash Requisition"), "Project Requisition");
			create(__("Claim"), "Project Claim");
			create(__("Site Report"), "Site Report");
		}
		if (stage === "Execution") {
			create(__("Labour Schedule"), "Labour Schedule");
			create(__("Casual Sheet"), "Casual Sheet");
			create(__("Subcontract RFQ"), "Subcontract RFQ");
			create(__("Variation Order"), "Project Variation Order");
			create(__("Budget Revision"), "Project Budget Revision");
			create(__("Practical Completion Certificate"), "Project Completion Certificate", {
				project: frm.doc.name,
				certificate_type: "Practical Completion",
			});
		}
		if (stage === "Practical Completion") {
			create(__("Defect"), "Project Defect");
			create(__("Full Completion Certificate"), "Project Completion Certificate", {
				project: frm.doc.name,
				certificate_type: "Full Completion",
			});
		}

		const report = (label, name) => {
			frm.add_custom_button(label, () => frappe.set_route("query-report", name, project), __("View"));
		};
		report(__("Project Cost Report"), "Project Cost Report");
		report(__("Material Consumption"), "Project Material Consumption");
	},
});
