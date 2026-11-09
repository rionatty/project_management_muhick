# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Who decides a step can be named. Each role that decides one has a standard User Group, "<role> Approvers", made empty
so that everyone with the role decides as before, and the decisions on the workflows already on the site read it. Their
own conditions, and any change made to them on the site, are kept: nothing is rebuilt."""

import frappe

from project_management_muhick.setup.workflows import DECISIONS, approver_group, get_workflows, setup_approver_groups, with_named, workflow_name


def execute():
	roles = set()
	for doctype in get_workflows():
		name = workflow_name(doctype)
		if not frappe.db.exists("Workflow", name):
			continue
		workflow = frappe.get_doc("Workflow", name)
		changed = False
		for row in workflow.transitions:
			if row.action in DECISIONS and row.allowed:
				roles.add(row.allowed)
				if approver_group(row.allowed) not in (row.condition or ""):
					row.condition = with_named(row.condition, row.allowed)
					changed = True
		if changed:
			# a workflow the site has made unsavable keeps its steps as they were, everyone with the role deciding
			frappe.db.savepoint("named_approvers")
			try:
				workflow.flags.ignore_permissions = True
				workflow.save()
			except Exception:
				frappe.db.rollback(save_point="named_approvers")
				frappe.log_error(title=f"Named approvers: {name} left as it was")
	setup_approver_groups(roles)
