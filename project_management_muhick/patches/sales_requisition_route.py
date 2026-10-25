# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The bid security has a request of its own now, so the sales requisition goes back to its one route
(Head of Sales, then General Manager). Its workflow is rebuilt; the other workflows are left as the
site has them."""

from project_management_muhick.setup.workflows import setup_workflows


def execute():
	setup_workflows(force=True, doctypes=["Sales Requisition"])
