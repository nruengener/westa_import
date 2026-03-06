{
    "name": "WESTA Import",
    "summary": "Import Oxaion partner maps from a staging PostgreSQL database",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "license": "LGPL-3",
    "author": "WX",
    "depends": ["base", "westa_data"],
    "data": [
        "security/ir.model.access.csv",
        "views/westa_partner_import_wizard_views.xml",
        "views/westa_import_settings_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
}
