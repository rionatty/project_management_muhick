# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A milestone of an opportunity, from the lead to the project, the weight it carries in its progress
and what marks it reached. The list is the business's own: the opportunities still being bid follow it
as soon as it changes, and decided ones keep the milestones they had."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.overrides.crm import IN_PROGRESS, refresh_bid_status


class OpportunityMilestone(Document):
	def validate(self):
		if setting_up():
			return
		others = frappe.get_all("Opportunity Milestone", filters={"disabled": 0, "name": ("!=", self.name or "")}, pluck="weight")
		total = sum(flt(weight) for weight in others) + (0 if self.disabled else flt(self.weight))
		if abs(total - 100) > 0.001:
			frappe.msgprint(
				_("The milestones in use weigh {0}% together. Progress is worked out from that total, but at 100% each weight reads as its share.").format(
					flt(total, 2)
				),
				indicator="orange",
				alert=True,
			)

	def on_update(self):
		if not setting_up():
			refresh_open_bids(open_bids())

	def on_trash(self):
		# off the opportunities still being bid; decided ones keep it in their history (disable it instead)
		self.flags.open_bids = open_bids()
		if self.flags.open_bids:
			frappe.db.delete(
				"Opportunity Milestone Line", {"milestone": self.name, "parenttype": "Opportunity", "parent": ("in", self.flags.open_bids)}
			)

	def after_delete(self):
		refresh_open_bids(self.flags.open_bids or [])


def setting_up() -> bool:
	return bool(frappe.flags.in_install or frappe.flags.in_patch or frappe.flags.in_migrate)


def open_bids() -> list:
	return frappe.get_all("Opportunity", filters={"sales_stage": ("in", IN_PROGRESS)}, pluck="name")


def refresh_open_bids(names):
	"""The opportunities still being bid follow the list at once."""
	for name in names:
		refresh_bid_status(name)
