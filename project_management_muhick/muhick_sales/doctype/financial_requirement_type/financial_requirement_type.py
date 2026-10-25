# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A kind of money a bid can need. Its kind decides where a financial requirement line of this type
goes: a Cost into the sales requisition, the Bid Security and its expenses into the bid security
request, a Contract Security into the project handover."""

from frappe.model.document import Document


class FinancialRequirementType(Document):
	pass
