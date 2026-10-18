# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

from frappe import _


def get_project_dashboard(data):
	"""Show the Muhick project documents on the Project form's Connections tab."""
	data.setdefault("transactions", []).extend(
		[
			{"label": _("Handover and Planning"), "items": ["Project Handover", "Project BOQ", "Project Activity Plan"]},
			{"label": _("Budget"), "items": ["Project Budget", "Project Budget Revision", "Project Requisition"]},
			{"label": _("Labour and Subcontracts"), "items": ["Labour Schedule", "Casual Sheet", "Subcontract RFQ", "Subcontract Agreement", "Service Receipt Note"]},
			{"label": _("Claims and Completion"), "items": ["Project Claim", "Project Variation Order", "Retention Release", "Project Completion Certificate", "Project Defect"]},
			{"label": _("Site Records"), "items": ["Site Report", "Site Meeting", "Project Document", "Project Equipment Allocation", "Project Warranty"]},
		]
	)
	return data
