"""Shared, bounded PostgreSQL schema evidence; never source row values."""

import hashlib
import json
from typing import Literal

from axis_api.connectors import csv_header_fingerprint

SchemaFingerprintVersion = Literal["column_names_v1", "postgres_schema_v2"]
POSTGRES_SCHEMA_VERSION = "postgres_schema_v2"
MAX_SCHEMA_COLUMNS = 1024


def postgres_schema_fingerprint(
    columns: list[tuple], version: str = POSTGRES_SCHEMA_VERSION
) -> str:
    if version == "column_names_v1":
        return csv_header_fingerprint([str(column[0]) for column in columns])
    if version != POSTGRES_SCHEMA_VERSION:
        raise ValueError("schema_version_incompatible")
    encoded = json.dumps([version, columns], separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_postgres_schema(
    cursor, schema: str, table: str, limit: int = MAX_SCHEMA_COLUMNS
) -> list[tuple]:
    cursor.execute(
        "SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), "
        "a.attnotnull, EXISTS (SELECT 1 FROM pg_catalog.pg_index i "
        "WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY(i.indkey)), "
        "a.attidentity, a.attgenerated "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 "
        "AND NOT a.attisdropped ORDER BY a.attnum LIMIT %s",
        (schema, table, limit + 1),
    )
    return [tuple(row) for row in cursor.fetchall()]
