// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Retention Register"] = {
	filters: [
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{
			fieldname: "retention",
			label: __("Retention"),
			fieldtype: "Select",
			options: ["All", "Held by Clients", "Held on Subcontractors"],
			default: "All",
		},
		{ fieldname: "only_outstanding", label: __("Only Still Held"), fieldtype: "Check", default: 1 },
	],
};
