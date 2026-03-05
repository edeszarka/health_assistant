"""LLM chat service via Ollama with bilingual (HU/EN) system prompt."""
from __future__ import annotations

import httpx

from backend.config import settings


SYSTEM_PROMPT_TEMPLATE = """You are a knowledgeable personal health assistant. Help the user understand their lab results,
health trends, blood pressure readings, and preventive care needs.
You handle text in Hungarian and English — always respond in the same language the user writes in.

User Profile:
- Age: {age}, Sex: {sex}
- Smoking: {smoking}
- BP medication: {bp_medication}

Family History:
{family_history_summary}

Recent Lab Flags (out of range):
{flagged_values}

Blood Pressure (30-day average):
{bp_summary}

Risk Scores:
- Framingham 10-year cardiovascular risk: {framingham}%
- FINDRISC diabetes risk score: {findrisc}

Relevant health context:
{rag_context}

Rules:
- Always reference specific values from the user's actual data
- Explain what flagged values COULD indicate — never diagnose
- Recommend which specialist to consult when values warrant it
- When you cite health information, note that it comes from MedlinePlus (NIH)
- End any health advice with: "Please consult your doctor to confirm."
- If the user writes in Hungarian, respond entirely in Hungarian"""


class LLMService:
    """Sends chat requests to Ollama and returns the text reply."""

    def __init__(self) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model

    async def chat(
        self,
        message: str,
        conversation_history: list[dict],
        context: str,
        user_profile: object | None = None,
        risk_scores: dict | None = None,
    ) -> str:
        """Send a message to Ollama and return the LLM reply.

        Args:
            message: The user's latest message.
            conversation_history: List of {"role": ..., "content": ...} dicts.
            context: RAG-assembled context string.
            user_profile: UserProfile ORM row or None.
            risk_scores: Dict with framingham and findrisc keys.

        Returns:
            The assistant's reply as a plain string.
        """
        profile = user_profile
        rs = risk_scores or {}

        system_content = SYSTEM_PROMPT_TEMPLATE.format(
            age=getattr(profile, "age", "Unknown"),
            sex=getattr(profile, "sex", "Unknown"),
            smoking=getattr(profile, "smoking", False),
            bp_medication=getattr(profile, "bp_medication", False),
            family_history_summary="(See context below.)",
            flagged_values="(See context below.)",
            bp_summary="(See context below.)",
            framingham=rs.get("framingham_risk_percent", "N/A"),
            findrisc=rs.get("findrisc_score", "N/A"),
            rag_context=context or "(No additional context available.)",
        )

        messages = [{"role": "system", "content": system_content}]
        for entry in conversation_history:
            messages.append(entry)
        messages.append({"role": "user", "content": message})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
        except Exception as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc


llm_service = LLMService()
