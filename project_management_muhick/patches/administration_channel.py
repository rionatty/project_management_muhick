# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The company's own needs, with no project, go the administration way whoever raises them, as local and international
procurement are for projects. A request now marks itself Administration Purchase and its approval reads the mark, so the
request's route is rebuilt. Requests already raised are marked the same way; documents already raised from them keep the
route they were on."""

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.workflows import setup_workflows


def execute():
	setup_custom_fields()
	frappe.db.sql(
		"""
		update `tabMaterial Request` set muhick_administration = 1
		where ifnull(material_request_type, '') != 'Material Transfer' and (
			muhick_request_origin = 'Administration'
			or (
				muhick_request_origin = 'User Department' and ifnull(muhick_project, '') = ''
				and name not in (select parent from `tabMaterial Request Item` where ifnull(project, '') != '')
			)
		)
		"""
	)
	setup_workflows(force=True, doctypes=["Material Request"])
