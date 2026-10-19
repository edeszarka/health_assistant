"""Recreate the user_profile table with the current schema, if it is empty.

The profile columns changed (birth year and month instead of age; weight and
waist moved to measurements; separate BP-medication and diabetes answers).
``create_all`` at startup never alters an existing table, so an old database
keeps the old columns. No profile could be created before this change, so the
table is expected to be empty; the script refuses to touch a table with rows.
Run inside the backend container; a dry run is the default:

    python -m scripts.migrate_user_profile          # report only
    python -m scripts.migrate_user_profile --apply  # drop and recreate

Prints the decision and a row count only, never profile values.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from database.connection import Base, engine
from models.db_models import UserProfile

TABLE = UserProfile.__tablename__
# A column that exists only in the current schema marks a migrated table.
MARKER_COLUMN = "birth_year"


def decide(columns: set[str] | None, row_count: int) -> str:
    """Decide what to do with the table.

    Args:
        columns: The table's current column names, or ``None`` if it is absent.
        row_count: Number of rows in the table (0 when absent).

    Returns:
        ``"create"`` when the table is absent, ``"up_to_date"`` when it already
        has the current schema, ``"refuse"`` when it is outdated but holds rows,
        and ``"recreate"`` when it is outdated and empty.
    """
    if columns is None:
        return "create"
    if MARKER_COLUMN in columns:
        return "up_to_date"
    if row_count > 0:
        return "refuse"
    return "recreate"


async def _inspect(conn: AsyncConnection) -> tuple[set[str] | None, int]:
    """Return the table's columns (``None`` if absent) and its row count."""
    def columns(sync_conn) -> set[str] | None:
        inspector = inspect(sync_conn)
        if not inspector.has_table(TABLE):
            return None
        return {col["name"] for col in inspector.get_columns(TABLE)}

    found = await conn.run_sync(columns)
    if found is None:
        return None, 0
    # TABLE is a module constant, not user input.
    count = (await conn.execute(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one()  # nosec B608
    return found, int(count)


async def main(apply: bool) -> int:
    """Run the migration; returns the process exit code."""
    async with engine.begin() as conn:
        columns, row_count = await _inspect(conn)
        decision = decide(columns, row_count)
        print(f"{TABLE}: rows={row_count} decision={decision}")
        if decision == "refuse":
            print("Refusing: the table holds rows; migrate them by hand.")
            return 1
        if decision == "up_to_date" or not apply:
            if not apply and decision != "up_to_date":
                print("Dry run: nothing written. Re-run with --apply.")
            return 0
        if decision == "recreate":
            await conn.run_sync(Base.metadata.tables[TABLE].drop)
        await conn.run_sync(Base.metadata.tables[TABLE].create)
        print(f"{TABLE}: created with the current schema.")
    return 0


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--apply", action="store_true", help="drop and recreate (default: dry run)")
    sys.exit(asyncio.run(main(cli.parse_args().apply)))
