# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A line quoted with VAT keeps the VAT rate it was worked out at, so a later change of the rate leaves it be. The
lines already quoted with VAT take today's rate."""

import frappe

from project_management_muhick.muhick_projects.estimate import DEFAULTS
from project_management_muhick.utils.common import setting


def execute():
	frappe.db.sql(
		"update `tabProject Budget Line` set vat_percent = %s where rate_includes_vat = 1 and ifnull(vat_percent, 0) = 0",
		(setting("vat_percent", DEFAULTS["vat_percent"]),),
	)
