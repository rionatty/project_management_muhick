# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_defaults
from project_management_muhick.setup.roles import setup_role_profiles, setup_roles, setup_standard_permissions
from project_management_muhick.setup.workflows import setup_workflows

# ERPNext's own desk icon for its Projects workspace
STANDARD_PROJECTS_ICON = "Projects"


def after_install():
	setup()
	setup_defaults()


def after_migrate():
	setup()


def before_uninstall():
	show_standard_projects_icon(True)


def setup():
	"""Safe to run any number of times: creates what is missing and leaves the rest alone."""
	setup_roles()
	setup_custom_fields()
	setup_role_profiles()
	setup_standard_permissions()
	setup_workflows()
	show_standard_projects_icon(False)
	frappe.clear_cache()


def show_standard_projects_icon(show):
	"""One projects icon on the desk. This app's sidebar carries everything ERPNext's Projects
	workspace has (timesheets, activity types, project types, settings and its reports), so
	ERPNext's Projects icon is hidden while the app is installed and shown again on uninstall."""
	hidden = 0 if show else 1
	if frappe.db.exists("Desktop Icon", STANDARD_PROJECTS_ICON):
		if frappe.db.get_value("Desktop Icon", STANDARD_PROJECTS_ICON, "hidden") != hidden:
			frappe.db.set_value("Desktop Icon", STANDARD_PROJECTS_ICON, "hidden", hidden)
