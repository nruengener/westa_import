# WESTA Import Addon

Imports `res.partner` from external PostgreSQL staging/mapping tables (`oxaion_map.map_res_partner_*`) via Odoo ORM.

This addon is the Odoo-side consumer for the partner-migration pipeline maintained in `db2discovery`.
The upstream project extracts partner data from Oxaion/DB2, loads it into a separate PostgreSQL staging database, builds normalized Odoo-facing map tables, and this addon imports those map rows into `res.partner`.

## Role In The Project

End-to-end flow:

1. DB2/Oxaion source data is extracted into PostgreSQL staging tables (`oxaion_stg.*`).
2. Mapping logic materializes Odoo-facing partner tables in `oxaion_map.*` and reject tables in `oxaion_err.*`.
3. This addon connects read-only to that staging PostgreSQL database.
4. This addon imports parents first, then contacts, then child addresses into Odoo via ORM.

This means the addon is not responsible for discovery, raw extraction, or mapping decisions. Those stay in the `db2discovery/odoo_partner` pipeline.

## Features

- Manual run via wizard/button (`WESTA Import > Partner Import`)
- Read-only PostgreSQL DSN to a separate staging database
- Optional tenant filter (`legacy_faad`, e.g. `W01`)
- Batch processing (`batch_size`)
- Global cap (`max_rows`, `0` = unlimited)
- VAT policy (`blank`, `drop`, `keep`)
- Optional child-address import
- Cron-ready (`WESTA Partner Import`, disabled by default)
- Upsert by `x_oxaion_id` from `westa_data`

## Required configuration via `ir.config_parameter`

- `westa_import.staging_pg_dsn` (PostgreSQL DSN for the staging DB; required)

## Optional configuration via `ir.config_parameter`

- `westa_import.partner_map_schema` (default: `oxaion_map`)
- `westa_import.partner_map_table_parent` (default: `map_res_partner_parents`)
- `westa_import.partner_map_table_contact` (default: `map_res_partner_contacts`)
- `westa_import.partner_map_table_address` (default: `map_res_partner_child_addresses`)
- `westa_import.legacy_faad` (default: empty)
- `westa_import.batch_size` (default: `1000`)
- `westa_import.max_rows` (default: `0`)
- `westa_import.vat_invalid_action` (default: `blank`)
- `westa_import.include_addresses` (default: `1`)

## Source Contract

The addon expects the staging PostgreSQL database to expose these map tables:

- `oxaion_map.map_res_partner_parents`
- `oxaion_map.map_res_partner_contacts`
- `oxaion_map.map_res_partner_child_addresses`

Expected row contract:

- `x_oxaion_id` is the stable upsert key and must be unique per logical partner record.
- `x_oxaion_parent_id` is required for contacts and child addresses when a parent relation should be created.
- `country_id` must already be Odoo-compatible before import: either a 2-letter country code or empty.
- `function` must already be Odoo-facing text or empty; raw Oxaion code values are not part of the import contract.
- `company_type`, `is_company`, `type`, `active`, `customer_rank`, and `supplier_rank` should already be normalized for Odoo.
- name fallback columns (`name`, `legacy_name1`, `legacy_name2`, `firstname`, `lastname`) may be present; the importer picks the first non-empty value.
- `legacy_faad` may be present and is used for optional tenant filtering.

The importer is tolerant of missing optional columns because it introspects the source table and selects `NULL` for absent fields. The required business contract is on the semantic fields above, not on every physical column being present.

## Odoo-Side Contract

- `westa_data` must be installed so `res.partner.x_oxaion_id` exists.
- `x_oxaion_id` is the idempotent import key for create/update behavior.
- Parents must be importable before dependent contacts and addresses.
- Contacts/addresses whose parent is not yet resolvable in Odoo are skipped.
- The addon writes through the Odoo ORM; it does not write back to the staging database.

## Security And Operations

- The staging PostgreSQL user should have read-only access to `oxaion_map.*`.
- The addon should not be pointed at raw staging tables (`oxaion_stg.*`) or reject tables as primary input.
- A normal run order is:
  1. refresh staging DB from DB2
  2. rebuild `oxaion_map.*`
  3. run this Odoo import
- This addon does not import from CSV files.

## Notes

- Parent records are imported first, then contacts, then child addresses.
- Contacts/addresses without resolvable parent are skipped.
- Odoo must have `westa_data` installed so `res.partner.x_oxaion_id` exists.
- The staging PostgreSQL user should have read-only access to `oxaion_map.*`.
