# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Opportunities use the business's lists: the types of work (Opportunity Type) and the bid's stages
(Sales Stage). ERPNext's sample values that nothing uses are removed."""

from project_management_muhick.setup.defaults import setup_crm_lists


def execute():
	setup_crm_lists()
