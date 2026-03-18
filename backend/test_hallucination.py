import asyncio
from config import settings
from services.llm_service import llm_service


async def main():
    message = "how many steps did I do on 2025.12.10?"

    # Simulate what chat.py does:

    metrics_summary = """
=== Top 10 Step Days (last 18 months) ===
  2024-09-15: 25,000 steps
  2024-10-01: 22,000 steps
  2025-01-05: 21,500 steps
  2025-06-12: 20,100 steps
  2025-07-20: 19,800 steps
  2025-08-05: 19,500 steps
  2025-11-10: 18,900 steps
  2025-11-20: 18,500 steps
  2026-01-02: 18,000 steps
  2026-02-15: 17,500 steps

=== Monthly Step Averages (last 18 months) ===
  2026-03: 316 avg steps/day (best day: 733, data from 9 days)
  2026-02: 3,963 avg steps/day (best day: 14,520, data from 29 days)
  2026-01: 5,004 avg steps/day (best day: 11,779, data from 31 days)
  2025-12: 7,070 avg steps/day (best day: 15,189, data from 31 days)
  2025-11: 5,783 avg steps/day (best day: 14,224, data from 30 days)
    """

    print("Testing LLM with prompt...")
    reply = await llm_service.chat(
        message=message,
        conversation_history=[],
        context="",
        user_profile=None,
        query_type="general",
        health_metrics_summary=metrics_summary,
        flagged_values="No flagged lab values on record.",
        bp_summary="No blood pressure readings in last 30 days.",
        family_history_summary="No family history recorded.",
    )

    print("\nLLM Reply:")
    print(reply)


if __name__ == "__main__":
    asyncio.run(main())
