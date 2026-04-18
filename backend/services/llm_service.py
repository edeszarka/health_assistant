"""LLM chat service via Ollama with bilingual (HU/EN) system prompt."""
from __future__ import annotations

import httpx

from config import settings


# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

# Standard prompt — /no_think disables chain-of-thought for speed on CPU
_BASE_PROMPT = """/no_think

You are a knowledgeable personal health assistant. Help the user understand their lab results,
health trends (Samsung Health and Zepp Life wearable data), blood pressure, and preventive care.

LANGUAGE RULE: The user is writing in {user_language}. You MUST reply ENTIRELY in {user_language}.
Do not switch languages. Even if the context data contains Hungarian or English medical terms,
your response must be in {user_language} only.

User Profile:
- Age: {age}, Sex: {sex}
- Height: {height} cm, Waist: {waist} cm
- Smoking: {smoking}
- BP medication: {bp_medication}
- History of high glucose: {high_glucose}
- Daily vegetables: {vegetables}

Family History:
{family_history_summary}

Lab Results and Trends (flagged values, rising/falling trends, key risk score inputs):
{flagged_values}

Blood Pressure:
{bp_summary}

Samsung Health and Wearable Metrics:
{health_metrics_summary}

Risk Scores:
- Framingham 10-year cardiovascular risk: {framingham}%
- FINDRISC diabetes risk score: {findrisc}
{findrisc_hypothetical_line}{framingham_hypothetical_line}
Additional medical context (from NIH MedlinePlus):
{rag_context}

Rules:
- Always reference specific values from the user's data shown above — quote the actual numbers
- If the user asks about steps, HR, sleep, cholesterol or any metric, find it above and cite it
- Explain what flagged or trending values COULD indicate — never diagnose
- Recommend which specialist to consult when values warrant it
- When citing health information, note it comes from MedlinePlus (NIH)
- End health advice with: "Please consult your doctor to confirm."
- CRITICAL: Respond only in {user_language}
- NEVER calculate risk scores yourself. If a hypothetical recalculation is shown above, present that pre-computed result to the user."""


# Thinking prompt — used for risk_analysis query type, allows deeper reasoning
# Note: identical to _BASE_PROMPT for now — both use /no_think for CPU performance.
# On a GPU setup, remove /no_think here to enable deeper reasoning for risk analysis.
_BASE_PROMPT_THINKING = """/no_think
You are a knowledgeable personal health assistant. Help the user understand their lab results,
health trends (Samsung Health and Zepp Life wearable data), blood pressure, and preventive care.

LANGUAGE RULE: The user is writing in {user_language}. You MUST reply ENTIRELY in {user_language}.
Do not switch languages. Even if the context data contains Hungarian or English medical terms,
your response must be in {user_language} only.

User Profile:
- Age: {age}, Sex: {sex}
- Height: {height} cm, Waist: {waist} cm
- Smoking: {smoking}
- BP medication: {bp_medication}
- History of high glucose: {high_glucose}
- Daily vegetables: {vegetables}

Family History:
{family_history_summary}

Lab Results and Trends (flagged values, rising/falling trends, key risk score inputs):
{flagged_values}

Blood Pressure:
{bp_summary}

Samsung Health and Wearable Metrics:
{health_metrics_summary}

Risk Scores:
- Framingham 10-year cardiovascular risk: {framingham}%
- FINDRISC diabetes risk score: {findrisc}
{findrisc_hypothetical_line}{framingham_hypothetical_line}
Additional medical context (from NIH MedlinePlus):
{rag_context}

Rules:
- Always reference specific values from the user's data shown above — quote the actual numbers
- If the user asks about steps, HR, sleep, cholesterol or any metric, find it above and cite it
- Explain what flagged or trending values COULD indicate — never diagnose
- Recommend which specialist to consult when values warrant it
- When citing health information, note it comes from MedlinePlus (NIH)
- End health advice with: "Please consult your doctor to confirm."
- CRITICAL: Respond only in {user_language}
- NEVER calculate risk scores yourself. If a hypothetical recalculation is shown above, present that pre-computed result to the user."""


# ---------------------------------------------------------------------------
# LLMService
# ---------------------------------------------------------------------------

class LLMService:
    """Sends chat requests to Ollama and returns the text reply.

    Responsibility: format the system prompt and call Ollama.
    Never fetches data from the database — all context is passed in.
    """

    def __init__(self) -> None:
        """Initializes the LLMService with Ollama configuration settings."""
        self._base_url = settings.ollama_base_url
        self._model    = settings.ollama_model

    async def chat(
        self,
        message: str,
        conversation_history: list[dict],
        context: str,
        user_profile: object | None = None,
        risk_scores: dict | None = None,
        query_type: str = "general",
        user_language: str = "English",
        health_metrics_summary: str = "",
        flagged_values: str = "",
        bp_summary: str = "",
        family_history_summary: str = "",
    ) -> str:
        """Send a message to Ollama and return the LLM reply.

        Args:
            message: The user's latest message.
            conversation_history: List of {"role": ..., "content": ...} dicts.
            context: RAG context string (medical knowledge, not personal data).
            user_profile: UserProfile ORM row or None.
            risk_scores: Dict with framingham_risk_percent and findrisc_score.
            query_type: "general" or "risk_analysis" (enables thinking mode).
            user_language: "English" or "Hungarian" — detected from message.
            health_metrics_summary: Steps, HR, sleep, weight from Samsung/Zepp.
            flagged_values: Lab results with trends and flag status.
            bp_summary: Blood pressure readings.
            family_history_summary: Family medical history entries.

        Returns:
            The generated response from the assistant as a plain string.

        Raises:
            RuntimeError: If the request to the Ollama API fails or returns an error.
        """
        profile = user_profile
        rs      = risk_scores or {}

        template = (
            _BASE_PROMPT_THINKING if query_type == "risk_analysis"
            else _BASE_PROMPT
        )

        # Build optional hypothetical score lines (empty string if not present)
        findrisc_hypo   = rs.get("findrisc_hypothetical", "")
        framingham_hypo = rs.get("framingham_hypothetical", "")
        findrisc_hypothetical_line   = f"- FINDRISC hypothetical: {findrisc_hypo}\n" if findrisc_hypo else ""
        framingham_hypothetical_line = f"- Framingham hypothetical: {framingham_hypo}\n" if framingham_hypo else ""

        system_content = template.format(
            user_language=user_language,
            age=getattr(profile, "age", "Unknown"),
            sex=getattr(profile, "sex", "Unknown"),
            height=getattr(profile, "height_cm", "Unknown"),
            waist=getattr(profile, "waist_cm", "Unknown"),
            smoking=getattr(profile, "smoking", False),
            bp_medication=getattr(profile, "bp_medication", False),
            high_glucose=getattr(profile, "high_glucose_history", False),
            vegetables=getattr(profile, "vegetables_daily", False),
            family_history_summary=family_history_summary or "No family history recorded.",
            flagged_values=flagged_values or "No lab results on record.",
            bp_summary=bp_summary or "No blood pressure readings recorded.",
            health_metrics_summary=health_metrics_summary or "No wearable / Samsung Health data available.",
            framingham=rs.get("framingham_risk_percent", "N/A"),
            findrisc=rs.get("findrisc_score", "N/A"),
            findrisc_hypothetical_line=findrisc_hypothetical_line,
            framingham_hypothetical_line=framingham_hypothetical_line,
            rag_context=context or "(No additional medical context available.)",
        )

        messages = [{"role": "system", "content": system_content}]
        for entry in conversation_history:
            messages.append(entry)
        messages.append({"role": "user", "content": message})

        # Use a much smaller predict limit for general queries to prevent long generation on slower hardware
        num_predict = 1024 if query_type == "risk_analysis" else 512

        payload = {
            "model":   self._model,
            "messages": messages,
            "stream":  False,
            "options": {
                "num_predict": num_predict
            }
        }
        timeout = 1800.0 if query_type == "risk_analysis" else 1000.0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
