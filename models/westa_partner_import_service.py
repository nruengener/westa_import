import logging
import re
from collections import defaultdict
from contextlib import closing

from odoo import _, api, models
from odoo.exceptions import UserError

try:
    import psycopg2
    from psycopg2 import extras as psycopg2_extras
except Exception:  # pragma: no cover - dependency varies by Odoo runtime
    psycopg2 = None
    psycopg2_extras = None


_logger = logging.getLogger(__name__)


class WestaPartnerImportService(models.AbstractModel):
    _name = "westa.partner.import.service"
    _description = "WESTA Partner Import Service"

    DEFAULT_SCHEMA = "oxaion_map"
    DEFAULT_TABLES = {
        "parent": "map_res_partner_parents",
        "contact": "map_res_partner_contacts",
        "address": "map_res_partner_child_addresses",
    }

    def run_import(
        self,
        legacy_faad=None,
        batch_size=1000,
        max_rows=0,
        vat_invalid_action="blank",
        include_addresses=True,
    ):
        if batch_size <= 0:
            raise UserError(_("batch_size must be > 0"))
        if max_rows < 0:
            raise UserError(_("max_rows must be >= 0"))
        if vat_invalid_action not in {"blank", "drop", "keep"}:
            raise UserError(_("vat_invalid_action must be one of blank, drop, keep"))

        staging_pg_dsn = (self._get_param("westa_import.staging_pg_dsn", "") or "").strip()
        if not staging_pg_dsn:
            raise UserError(
                _("Missing system parameter westa_import.staging_pg_dsn for the staging PostgreSQL database.")
            )

        schema = self._get_param("westa_import.partner_map_schema", self.DEFAULT_SCHEMA)
        tables = {
            "parent": self._get_param(
                "westa_import.partner_map_table_parent", self.DEFAULT_TABLES["parent"]
            ),
            "contact": self._get_param(
                "westa_import.partner_map_table_contact", self.DEFAULT_TABLES["contact"]
            ),
            "address": self._get_param(
                "westa_import.partner_map_table_address", self.DEFAULT_TABLES["address"]
            ),
        }

        self._validate_ident(schema, "schema")
        for kind, table in tables.items():
            self._validate_ident(table, f"table for {kind}")

        partner_env = self.env["res.partner"].sudo().with_context(
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_notrack=True,
        )

        stats = defaultdict(int)
        import_order = ["parent", "contact"]
        if include_addresses:
            import_order.append("address")

        with closing(self._connect_staging(staging_pg_dsn)) as staging_conn:
            for kind in import_order:
                if max_rows and stats["written_total"] >= max_rows:
                    stats["limit_hit"] = 1
                    break
                self._import_kind(
                    partner_env=partner_env,
                    staging_conn=staging_conn,
                    schema=schema,
                    table=tables[kind],
                    kind=kind,
                    legacy_faad=(legacy_faad or "").strip() or None,
                    batch_size=batch_size,
                    max_rows=max_rows,
                    vat_invalid_action=vat_invalid_action,
                    stats=stats,
                )

        stats["staging_schema"] = schema
        stats["legacy_faad_filter"] = (legacy_faad or "").strip() or "ALL"
        return dict(stats)

    @api.model
    def run_import_cron(self):
        legacy_faad = self._get_param("westa_import.legacy_faad", "") or None
        batch_size = int(self._get_param("westa_import.batch_size", "1000") or 1000)
        max_rows = int(self._get_param("westa_import.max_rows", "0") or 0)
        vat_invalid_action = self._get_param("westa_import.vat_invalid_action", "blank")
        include_addresses = (self._get_param("westa_import.include_addresses", "1") or "1") in {
            "1",
            "true",
            "True",
        }
        return self.run_import(
            legacy_faad=legacy_faad,
            batch_size=batch_size,
            max_rows=max_rows,
            vat_invalid_action=vat_invalid_action,
            include_addresses=include_addresses,
        )

    def _connect_staging(self, dsn):
        if psycopg2 is None or psycopg2_extras is None:
            raise UserError(
                _("Missing dependency 'psycopg2' in the Odoo environment. Install the PostgreSQL driver first.")
            )
        try:
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            return conn
        except Exception as exc:
            raise UserError(_("Failed to connect to staging PostgreSQL: %s") % exc) from exc

    def _import_kind(
        self,
        partner_env,
        staging_conn,
        schema,
        table,
        kind,
        legacy_faad,
        batch_size,
        max_rows,
        vat_invalid_action,
        stats,
    ):
        columns = self._table_columns(staging_conn, schema, table)
        select_sql = self._build_select_clause(columns)

        offset = 0
        while True:
            if max_rows:
                remaining = max_rows - stats["written_total"]
                if remaining <= 0:
                    stats["limit_hit"] = 1
                    break
                fetch_limit = min(batch_size, remaining)
            else:
                fetch_limit = batch_size

            rows = self._fetch_batch(
                staging_conn=staging_conn,
                schema=schema,
                table=table,
                select_sql=select_sql,
                legacy_faad=legacy_faad,
                limit=fetch_limit,
                offset=offset,
            )
            if not rows:
                break

            offset += len(rows)
            self._process_batch(
                partner_env=partner_env,
                rows=rows,
                kind=kind,
                vat_invalid_action=vat_invalid_action,
                stats=stats,
            )

            if len(rows) < fetch_limit:
                break

    def _process_batch(self, partner_env, rows, kind, vat_invalid_action, stats):
        partner_fields = set(partner_env._fields)
        xids = [r.get("x_oxaion_id") for r in rows if r.get("x_oxaion_id")]
        existing = {
            p["x_oxaion_id"]: p["id"]
            for p in partner_env.search_read(
                [("x_oxaion_id", "in", xids)], ["id", "x_oxaion_id"], limit=0
            )
            if p.get("x_oxaion_id")
        }

        parent_xids = [r.get("x_oxaion_parent_id") for r in rows if r.get("x_oxaion_parent_id")]
        parent_map = {}
        if parent_xids:
            parent_map = {
                p["x_oxaion_id"]: p["id"]
                for p in partner_env.search_read(
                    [("x_oxaion_id", "in", parent_xids)], ["id", "x_oxaion_id"], limit=0
                )
                if p.get("x_oxaion_id")
            }

        for row in rows:
            xid = (row.get("x_oxaion_id") or "").strip()
            if not xid:
                stats[f"skipped_missing_xid_{kind}"] += 1
                continue

            vals = self._vals_from_row(row=row, kind=kind, parent_map=parent_map)
            if vals is None:
                stats[f"skipped_parent_missing_{kind}"] += 1
                continue
            vals = self._filter_existing_fields(vals, partner_fields)

            vat = vals.get("vat")
            if vat:
                vals["vat"] = self._normalize_vat(vat, vals.get("country_id"))
                valid = self._is_valid_vat(vals["vat"])
                if not valid:
                    stats["invalid_vat_total"] += 1
                    if vat_invalid_action == "drop":
                        stats[f"dropped_invalid_vat_{kind}"] += 1
                        continue
                    if vat_invalid_action == "blank":
                        vals["vat"] = False
                        stats[f"blanked_invalid_vat_{kind}"] += 1
                    else:
                        stats[f"kept_invalid_vat_{kind}"] += 1

            try:
                if xid in existing:
                    partner_env.browse(existing[xid]).write(vals)
                    stats[f"updated_{kind}"] += 1
                else:
                    create_vals = dict(vals)
                    if "x_oxaion_id" in partner_fields:
                        create_vals["x_oxaion_id"] = xid
                    rec = partner_env.create(create_vals)
                    existing[xid] = rec.id
                    stats[f"created_{kind}"] += 1
                stats["written_total"] += 1
            except Exception as exc:
                _logger.exception(
                    "WESTA import failed for kind=%s xid=%s vals=%s",
                    kind,
                    xid,
                    vals,
                )
                raise UserError(
                    _("Failed to import %(kind)s record %(xid)s: %(error)s")
                    % {"kind": kind, "xid": xid, "error": exc}
                ) from exc

    def _vals_from_row(self, row, kind, parent_map):
        vals = {
            "name": self._pick_name(row),
            "company_type": (row.get("company_type") or "").strip() or ("company" if kind == "parent" else "person"),
            "is_company": self._to_bool(row.get("is_company"), default=(kind == "parent")),
            "type": self._normalize_partner_type(row.get("type"), kind),
            "street": row.get("street") or False,
            "street2": row.get("street2") or False,
            "zip": row.get("zip") or False,
            "city": row.get("city") or False,
            "phone": row.get("phone") or False,
            "mobile": row.get("mobile") or False,
            "email": row.get("email") or False,
            "vat": row.get("vat") or False,
            "function": row.get("function") or False,
            "active": self._to_bool(row.get("active"), default=True),
            "customer_rank": self._to_int(row.get("customer_rank")),
            "supplier_rank": self._to_int(row.get("supplier_rank")),
        }

        country_value = (row.get("country_id") or "").strip()
        country_id = self._resolve_country(country_value)
        if country_id:
            vals["country_id"] = country_id
        else:
            vals["country_id"] = False

        if kind != "parent":
            parent_xid = (row.get("x_oxaion_parent_id") or "").strip()
            parent_id = parent_map.get(parent_xid)
            if not parent_id:
                return None
            vals["parent_id"] = parent_id

        return vals

    def _filter_existing_fields(self, vals, existing_fields):
        return {key: value for key, value in vals.items() if key in existing_fields}

    def _fetch_batch(self, staging_conn, schema, table, select_sql, legacy_faad, limit, offset):
        where = ""
        params = []
        if legacy_faad:
            where = " WHERE UPPER(COALESCE(legacy_faad, '')) = %s"
            params.append(legacy_faad.upper())

        query = (
            f'SELECT {select_sql} FROM "{schema}"."{table}"{where} '
            'ORDER BY x_oxaion_id NULLS LAST LIMIT %s OFFSET %s'
        )
        params.extend([limit, offset])
        with staging_conn.cursor(cursor_factory=psycopg2_extras.RealDictCursor) as cr:
            cr.execute(query, tuple(params))
            return cr.fetchall()

    def _table_columns(self, staging_conn, schema, table):
        with staging_conn.cursor() as cr:
            cr.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            cols = {r[0] for r in cr.fetchall()}
        if not cols:
            raise UserError(_("Map table not found in staging DB: %s.%s") % (schema, table))
        return cols

    def _build_select_clause(self, cols):
        def expr(name):
            if name in cols:
                return f'"{name}"'
            return "NULL"

        aliases = [
            "x_oxaion_id",
            "x_oxaion_parent_id",
            "name",
            "company_type",
            "is_company",
            "type",
            "street",
            "street2",
            "zip",
            "city",
            "country_id",
            "phone",
            "mobile",
            "email",
            "vat",
            "function",
            "active",
            "customer_rank",
            "supplier_rank",
            "legacy_name1",
            "legacy_name2",
            "firstname",
            "lastname",
            "legacy_faad",
        ]
        return ", ".join(f"{expr(a)} AS {a}" for a in aliases)

    def _validate_ident(self, name, label):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", (name or "").strip()):
            raise UserError(_("Invalid SQL identifier for %s: %s") % (label, name))

    def _get_param(self, key, default):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _pick_name(self, row):
        for key in ("name", "legacy_name1", "legacy_name2", "firstname", "lastname"):
            value = (row.get(key) or "").strip()
            if value:
                return value
        return _("Unknown")

    def _normalize_partner_type(self, value, kind):
        v = (value or "").strip().lower()
        if v in {"contact", "invoice", "delivery", "other", "private"}:
            return v
        return "contact" if kind in {"parent", "contact"} else "other"

    def _to_bool(self, value, default=False):
        if value in (True, False):
            return value
        s = str(value or "").strip().lower()
        if not s:
            return default
        return s in {"1", "y", "yes", "true", "t"}

    def _to_int(self, value):
        s = str(value or "").strip()
        if not s:
            return 0
        try:
            return int(float(s))
        except Exception:
            return 0

    def _resolve_country(self, country_value):
        if not country_value:
            return False
        if country_value.isdigit():
            country = self.env["res.country"].sudo().browse(int(country_value))
            return country.id if country.exists() else False
        country = self.env["res.country"].sudo().search([("code", "=", country_value.upper())], limit=1)
        return country.id or False

    def _normalize_vat(self, vat_raw, country_code_or_id):
        vat = re.sub(r"[^A-Za-z0-9]+", "", (vat_raw or "").strip()).upper()
        if not vat:
            return ""

        cc = ""
        if isinstance(country_code_or_id, int):
            country = self.env["res.country"].sudo().browse(country_code_or_id)
            cc = (country.code or "").upper() if country.exists() else ""
        elif isinstance(country_code_or_id, str):
            cc = country_code_or_id.upper() if len(country_code_or_id) == 2 else ""

        if len(cc) != 2:
            return vat
        if cc == "FR" and re.fullmatch(r"[A-Z0-9]{11}", vat):
            return f"FR{vat}"
        if cc == "IT" and re.fullmatch(r"[0-9]{11}", vat):
            return f"IT{vat}"
        if vat.startswith(cc):
            return vat
        return f"{cc}{vat}"

    def _is_valid_vat(self, vat):
        if not vat:
            return True
        try:
            from stdnum.eu import vat as eu_vat
        except Exception:
            return False
        try:
            return bool(eu_vat.is_valid(vat))
        except Exception:
            return False
