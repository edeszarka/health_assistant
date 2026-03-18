from sqlalchemy import select
from database.connection import SessionLocal
from models.db_models import BloodPressure


class BPService:
    async def add_reading(
        self, user_id: int, systolic: int, diastolic: int, pulse: int = None
    ):
        async with SessionLocal() as session:
            reading = BloodPressure(
                user_id=user_id, systolic=systolic, diastolic=diastolic, pulse=pulse
            )
            session.add(reading)
            await session.commit()
            return reading

    async def get_history(self, user_id: int):
        async with SessionLocal() as session:
            stmt = (
                select(BloodPressure)
                .where(BloodPressure.user_id == user_id)
                .order_by(BloodPressure.timestamp.desc())
            )
            result = await session.execute(stmt)
            return result.scalars().all()


bp_service = BPService()
