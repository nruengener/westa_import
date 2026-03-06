from odoo import _, fields, models
from odoo.exceptions import ValidationError


class WestaImportSettings(models.TransientModel):
    _name = "westa.import.settings"
    _description = "WESTA Import Settings"

    staging_pg_dsn = fields.Char(
        string="Staging PostgreSQL DSN",
        required=True,
        help=(
            "Connection string for the staging PostgreSQL database used by WESTA Import, "
            "for example: host=127.0.0.1 port=5432 dbname=westa_staging user=odoo_import password=secret"
        ),
    )

    def default_get(self, field_list):
        values = super().default_get(field_list)
        values["staging_pg_dsn"] = (
            self.env["ir.config_parameter"].sudo().get_param("westa_import.staging_pg_dsn", "") or ""
        )
        return values

    def action_save(self):
        self.ensure_one()
        dsn = (self.staging_pg_dsn or "").strip()
        if not dsn:
            raise ValidationError(_("Staging PostgreSQL DSN is required."))
        self.env["ir.config_parameter"].sudo().set_param("westa_import.staging_pg_dsn", dsn)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WESTA Import"),
                "message": _("Configuration saved."),
                "sticky": False,
                "type": "success",
            },
        }
