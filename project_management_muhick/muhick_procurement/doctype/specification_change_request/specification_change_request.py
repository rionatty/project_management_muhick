# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A formal request from operations to change a specification or quantity after the material
request or order was raised. Procurement is told at once, and the request stays on record."""

import frappe
from frappe import _
from frappe.model.document import Document

from project_management_muhick.utils.common import FINANCE_ROLES, PRM, PRO, notify, notify_roles


class SpecificationChangeRequest(Document):
	def before_insert(self):
		self.requested_by = frappe.session.user

	def validate(self):
		if not self.is_new() and self.has_value_changed("status") and self.status != "Open":
			self.responded_by = frappe.session.user

	def after_insert(self):
		roles = [PRM, PRO]
		if self.purchase_order:
			# an order already exists, so the change may affect what Finance has committed
			roles += list(FINANCE_ROLES)
		notify_roles(roles, _("Specification change requested: {0}").format(self.title), doc=self)

	def on_update(self):
		if not self.is_new() and self.has_value_changed("status"):
			notify([self.requested_by or self.owner], _("Specification change {0} is now {1}.").format(self.title, _(self.status)), doc=self)
