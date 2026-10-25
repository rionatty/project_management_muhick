# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Financial requirement types and sales requisition lines pick from a list now. The list starts
with the types that were fixed choices before, so every line already entered stays valid."""

from project_management_muhick.setup.defaults import setup_crm_lists


def execute():
	setup_crm_lists()
