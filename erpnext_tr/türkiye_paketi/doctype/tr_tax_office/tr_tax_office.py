# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class TRTaxOffice(Document):
    def validate(self) -> None:
        if not self.kod or not self.il:
            return
        existing = frappe.db.exists(
            "TR Tax Office",
            {"kod": self.kod, "il": self.il, "name": ("!=", self.name)},
        )
        if existing:
            frappe.throw(
                _("Aynı kod ve il kombinasyonu zaten var: {0} / {1}").format(self.kod, self.il)
            )
