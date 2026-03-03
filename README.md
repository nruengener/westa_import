# WESTA Import Addon

Imports `res.partner` from PostgreSQL mapping tables (`oxaion_map.map_res_partner_*`) via Odoo ORM.

## Features

- Manual run via wizard/button (`WESTA Import > Partner Import`)
- Optional tenant filter (`legacy_faad`, e.g. `W01`)
- Batch processing (`batch_size`)
- Global cap (`max_rows`, `0` = unlimited)
- VAT policy (`blank`, `drop`, `keep`)
- Optional child-address import
- Cron-ready (`WESTA Partner Import`, disabled by default)

## Configuration via `ir.config_parameter` (optional)

- `westa_import.partner_map_schema` (default: `oxaion_map`)
- `westa_import.partner_map_table_parent` (default: `map_res_partner_parents`)
- `westa_import.partner_map_table_contact` (default: `map_res_partner_contacts`)
- `westa_import.partner_map_table_address` (default: `map_res_partner_child_addresses`)
- `westa_import.legacy_faad` (default: empty)
- `westa_import.batch_size` (default: `1000`)
- `westa_import.max_rows` (default: `0`)
- `westa_import.vat_invalid_action` (default: `blank`)
- `westa_import.include_addresses` (default: `1`)

## Notes

- Parent records are imported first, then contacts, then child addresses.
- Upsert key is `x_oxaion_id`.
- Contacts/addresses without resolvable parent are skipped.
