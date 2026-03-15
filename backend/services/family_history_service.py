from sqlalchemy import select
from database.connection import SessionLocal
from models.db_models import FamilyHistory

class FamilyHistoryService:
    async def add_entry(self, user_id: int, relative: str, condition: str, age: int = None):
        async with SessionLocal() as session:
            entry = FamilyHistory(
                user_id=user_id,
                relative_type=relative,
                condition=condition,
                age_at_onset=age
            )
            session.add(entry)
            await session.commit()
            return entry

    async def get_entries(self, user_id: int):
        async with SessionLocal() as session:
            stmt = select(FamilyHistory).where(FamilyHistory.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalars().all()

family_history_service = FamilyHistoryService()
