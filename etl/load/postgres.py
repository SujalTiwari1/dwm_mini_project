"""PostgreSQL helpers: engine, schema creation, truncate, and bulk COPY."""
from sqlalchemy import create_engine

from .. import config as C


def get_engine():
    return create_engine(C.get_database_url(), future=True)


def run_sql_file(conn, path):
    """Execute a (multi-statement, parameter-free) SQL script on a SQLAlchemy connection."""
    conn.exec_driver_sql(path.read_text(encoding="utf-8"))


def create_schema(conn):
    run_sql_file(conn, C.SQL_DIR / "schema.sql")


def truncate_all(conn):
    """Full-rebuild strategy: empty every warehouse table (facts and dimensions in one statement)."""
    tables = ", ".join(f"{C.SCHEMA}.{t}" for t in C.FACT_TABLES + C.DIM_TABLES)
    conn.exec_driver_sql(f"TRUNCATE TABLE {tables}")


def copy_dataframe(conn, table, df):
    """Stream a DataFrame into schema.table with COPY ... FROM STDIN (CSV), in chunks. Returns rows copied."""
    cols = ", ".join(df.columns)
    raw = conn.connection.driver_connection         # psycopg connection sharing the SQLAlchemy transaction
    with raw.cursor() as cur:
        with cur.copy(f"COPY {C.SCHEMA}.{table} ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
            for start in range(0, len(df), C.COPY_CHUNK_ROWS):
                chunk = df.iloc[start:start + C.COPY_CHUNK_ROWS]
                copy.write(chunk.to_csv(index=False, header=False, float_format="%.2f"))
    return len(df)


def drop_secondary_indexes(conn):
    """Bulk-load optimisation: drop the non-constraint (ix_*) indexes before COPY; create_schema() rebuilds them
    afterwards because schema.sql is idempotent. PK / UNIQUE / FK / CHECK constraints stay in place."""
    names = [r[0] for r in conn.exec_driver_sql(
        f"SELECT indexname FROM pg_indexes WHERE schemaname = '{C.SCHEMA}' AND starts_with(indexname, 'ix_')").fetchall()]
    for n in names:
        conn.exec_driver_sql(f"DROP INDEX IF EXISTS {C.SCHEMA}.{n}")
    return len(names)


def drop_fact_foreign_keys(conn):
    """Bulk-load optimisation: per-row FK triggers dominate COPY time. Save the fact tables' FK definitions
    (names + definitions read from the catalog, so schema.sql stays the single source of truth) and drop them."""
    facts = ", ".join(f"'{t}'" for t in C.FACT_TABLES)
    saved = conn.exec_driver_sql(
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        f"WHERE c.contype = 'f' AND n.nspname = '{C.SCHEMA}' AND t.relname IN ({facts}) ORDER BY 1, 2").fetchall()
    for table, name, _ in saved:
        conn.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    return [tuple(r) for r in saved]


def restore_foreign_keys(conn, saved):
    """Re-add the saved FKs; PostgreSQL validates every loaded row, so integrity is fully enforced at commit."""
    for table, name, definition in saved:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")


def analyze_all(conn):
    for t in C.DIM_TABLES + C.FACT_TABLES:
        conn.exec_driver_sql(f"ANALYZE {C.SCHEMA}.{t}")
