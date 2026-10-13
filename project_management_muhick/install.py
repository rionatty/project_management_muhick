# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_defaults
from project_management_muhick.setup.roles import setup_role_profiles, setup_roles, setup_standard_permissions
from project_management_muhick.setup.workflows import setup_workflows


def after_install():
	setup()
	setup_defaults()


def after_migrate():
	setup()


def setup():
	"""Safe to run any number of times: creates what is missing and leaves the rest alone."""
	setup_roles()
	setup_custom_fields()
	setup_role_profiles()
	setup_standard_permissions()
	setup_workflows()
	frappe.clear_cache()
