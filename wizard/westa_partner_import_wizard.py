from odoo import _, fields, models


class WestaPartnerImportWizard(models.TransientModel):
    _name = "westa.partner.import.wizard"
    _description = "WESTA Partner Import"

    legacy_faad = fields.Char(
        string="Legacy Mandant (FAAD)",
        help="Optional, z.B. W01. Leer = alle Mandanten.",
    )
    batch_size = fields.Integer(string="Batch Size", default=1000, required=True)
    max_rows = fields.Integer(string="Max Rows", default=0, required=True)
    vat_invalid_action = fields.Selection(
        selection=[("blank", "Blank"), ("drop", "Drop"), ("keep", "Keep")],
        default="blank",
        required=True,
    )
    include_addresses = fields.Boolean(string="Include Child Addresses", default=True)

    def action_run_import(self):
        self.ensure_one()
        stats = self.env["westa.partner.import.service"].run_import(
            legacy_faad=self.legacy_faad,
            batch_size=self.batch_size,
            max_rows=self.max_rows,
            vat_invalid_action=self.vat_invalid_action,
            include_addresses=self.include_addresses,
        )

        message = _(
            "Import finished. source=%(source)s, legacy_faad=%(legacy_faad)s, written_total=%(written_total)s, "
            "created_parent=%(created_parent)s, updated_parent=%(updated_parent)s, "
            "created_contact=%(created_contact)s, updated_contact=%(updated_contact)s, "
            "created_address=%(created_address)s, updated_address=%(updated_address)s, "
            "skipped_parent_missing=%(skipped_parent_missing)s"
        ) % {
            "source": stats.get("staging_schema", "?"),
            "legacy_faad": stats.get("legacy_faad_filter", "ALL"),
            "written_total": stats.get("written_total", 0),
            "created_parent": stats.get("created_parent", 0),
            "updated_parent": stats.get("updated_parent", 0),
            "created_contact": stats.get("created_contact", 0),
            "updated_contact": stats.get("updated_contact", 0),
            "created_address": stats.get("created_address", 0),
            "updated_address": stats.get("updated_address", 0),
            "skipped_parent_missing": (
                stats.get("skipped_parent_missing_contact", 0)
                + stats.get("skipped_parent_missing_address", 0)
            ),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WESTA Import"),
                "message": message,
                "sticky": False,
                "type": "success",
            },
        }
