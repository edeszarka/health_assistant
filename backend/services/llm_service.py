"""LLM chat service via Ollama with bilingual (HU/EN) system prompt."""
from __future__ import annotations

import json
import httpx

from config import settings


_BASE_PROMPT = """You are a health AI. Be brief (max 3 sentences).
Context:
- Age: {age}, Sex: {sex}, Smoke: {smoking}, BP Meds: {bp_medication}
- Family: {family_history_summary}
- Labs: {flagged_values}
- BP: {bp_summary}
- Metrics: {health_metrics_summary}
- Risk: CV {framingham}%, Diabetes {findrisc}
- Medline: {rag_context}
Rules: Use these values. Hungarian if user writes in HU. End with: "Consult your doctor." """


_RISK_ANALYSIS_ADDENDUM = " Reason step-by-step."


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
        query_type: str = "general",
        health_metrics_summary: str = "",
        flagged_values: str = "",
        bp_summary: str = "",
        family_history_summary: str = "",
    ) -> str:
        """Send a message to Ollama and return the LLM reply."""
        profile = user_profile
        rs = risk_scores or {}

        template = _BASE_PROMPT
        if query_type == "risk_analysis":
            template += _RISK_ANALYSIS_ADDENDUM
        
        user_message = f"/no_think {message}"

        system_content = template.format(
            age=getattr(profile, "age", "?"),
            sex=getattr(profile, "sex", "?"),
            smoking=getattr(profile, "smoking", False),
            bp_medication=getattr(profile, "bp_medication", False),
            family_history_summary=family_history_summary or "None",
            flagged_values=flagged_values or "None",
            bp_summary=bp_summary or "None",
            health_metrics_summary=health_metrics_summary or "None",
            framingham=rs.get("framingham_risk_percent", "N/A"),
            findrisc=rs.get("findrisc_score", "N/A"),
            rag_context=context or "N/A",
        )

        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        num_predict = 512 if query_type == "risk_analysis" else 150

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": num_predict,
                "num_ctx": 2048,
                "temperature": 0.1,
            },
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()


llm_service = LLMService()
