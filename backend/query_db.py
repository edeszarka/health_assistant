import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()


async def main():
    db_url = os.getenv("DATABASE_URL")
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
            SELECT recorded_at, value 
            FROM samsung_health_metrics 
            WHERE metric_type='steps' 
            ORDER BY value DESC
            LIMIT 15;
        """
            )
        )
        print("Top 15 step days:")
        for r in result.fetchall():
            print(r)


asyncio.run(main())
