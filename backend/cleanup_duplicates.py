"""Cleanup script to remove duplicate health metrics before applying UniqueConstraint."""
from __future__ import annotations

import asyncio
from sqlalchemy import text
from database.connection import engine


async def cleanup():
    print("Starting cleanup of duplicate metrics...")
    async with engine.begin() as conn:
        # This query finds rows where metric_type and recorded_at are identical,
        # and deletes all but the one with the smallest ID.
        query = text("""
            DELETE FROM samsung_health_metrics a
            USING samsung_health_metrics b
            WHERE a.id > b.id
              AND a.metric_type = b.metric_type
              AND a.recorded_at = b.recorded_at;
        """)
        result = await conn.execute(query)
        print(f"Cleanup complete. Removed {result.rowcount} duplicate rows.")


if __name__ == "__main__":
    asyncio.run(cleanup())
