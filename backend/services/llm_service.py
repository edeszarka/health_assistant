"""LLM chat service via Ollama with bilingual (HU/EN) system prompt."""
from __future__ import annotations

import httpx

from services.llm_service import llm_service, _detect_intent
from config import settings


_BASE_PROMPT = """You are a knowledgeable personal health assistant. Help the user understand their lab results,
health trends (including Samsung Health and Zepp Life), blood pressure readings, and preventive care needs.
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

Samsung Health & Wearable Metrics:
{health_metrics_summary}

Risk Scores:
- Framingham 10-year cardiovascular risk: {framingham}%
- FINDRISC diabetes risk score: {findrisc}

Additional context from health records:
{rag_context}

Rules:
- Always reference specific values from the user's actual data shown above
- If the user asks about steps, heart rate, sleep or any metric — look it up in the sections above and quote the actual numbers
- Explain what flagged values COULD indicate — never diagnose
- Recommend which specialist to consult when values warrant it
- When you cite health information, note that it comes from MedlinePlus (NIH)
- End any health advice with: "Please consult your doctor to confirm."
- If the user writes in Hungarian, respond entirely in Hungarian"""


_RISK_ANALYSIS_ADDENDUM = """

For this risk analysis query, reason carefully step by step:
1. Identify all relevant values from the user's data
2. Note which direction each value trends and by how much
3. Consider interactions between risk factors (e.g. high LDL + family CV history)
4. Quantify uncertainty — flag if data is old or incomplete
5. Only then summarize findings and recommendations"""


def _detect_intent(message: str) -> dict:
    """Detect which data domains are relevant to the user's query.
    
    Used in chat.py to decide which context sections to fetch from DB.
    Keyword-based — no LLM call needed.
    """
    msg = message.lower()
    domains = set()

    if any(w in msg for w in ["lépés", "steps", "walk", "aktivit", "kalória", "calorie", "sleep", "alvás", "hr", "pulzus", "szív"]):
        domains.add("activity")
    if any(w in msg for w in ["labor", "vérkép", "koleszterin", "lab", "blood", "glucose", "hba1c", "ferritin", "tsh"]):
        domains.add("labs")
    if any(w in msg for w in ["vérnyomás", "blood pressure", "bp", "szisztolés", "diastolic"]):
        domains.add("bp")
    if any(w in msg for w in ["család", "family", "history", "előzmény"]):
        domains.add("family")
    if not domains:
        # General question — load everything
        domains = {"activity", "labs", "bp", "family"}

    return {"domains": domains}


class LLMService:
    """Sends chat requests to Ollama and returns the text reply.

    Responsibility: format the system prompt and call Ollama.
    Never fetches data from the database — all context is passed in.
    """

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
        user_language: str = "English",  # kept for chat.py compatibility
        health_metrics_summary: str = "",
        flagged_values: str = "",
        bp_summary: str = "",
        family_history_summary: str = "",
    ) -> str:
        """Send a message to Ollama and return the LLM reply.

        Args:
            message: The user's latest message.
            conversation_history: List of {"role": ..., "content": ...} dicts.
            context: RAG-assembled context string.
            user_profile: UserProfile ORM row or None.
            risk_scores: Dict with framingham and findrisc keys.
            query_type: "general" or "risk_analysis" (enables thinking mode).
            user_language: Detected language — kept for API compatibility.
            health_metrics_summary: Pre-fetched Samsung/Zepp metrics as text.
            flagged_values: Pre-fetched out-of-range lab values as text.
            bp_summary: Pre-fetched blood pressure summary as text.
            family_history_summary: Pre-fetched family history as text.

        Returns:
            The assistant's reply as a plain string.

        Raises:
            RuntimeError: If the Ollama request fails.
        """
        profile = user_profile
        rs = risk_scores or {}

        # Build prompt: addendum is appended only for risk_analysis queries.
        # /no_think is placed in the user message (Qwen3-specific) to disable
        # chain-of-thought for general queries — halves response time on CPU.
        if query_type == "risk_analysis":
            template = _BASE_PROMPT + _RISK_ANALYSIS_ADDENDUM
            user_message = message
        else:
            template = _BASE_PROMPT
            user_message = f"/no_think {message}"

        system_content = template.format(
            age=getattr(profile, "age", "Unknown"),
            sex=getattr(profile, "sex", "Unknown"),
            smoking=getattr(profile, "smoking", False),
            bp_medication=getattr(profile, "bp_medication", False),
            family_history_summary=family_history_summary or "No family history recorded.",
            flagged_values=flagged_values or "No flagged lab values.",
            bp_summary=bp_summary or "No blood pressure data.",
            health_metrics_summary=health_metrics_summary or "No wearable/Samsung data available.",
            framingham=rs.get("framingham_risk_percent", "N/A"),
            findrisc=rs.get("findrisc_score", "N/A"),
            rag_context=context or "(No additional context available.)",
        )

        messages = [{"role": "system", "content": system_content}]
        for entry in conversation_history:
            messages.append(entry)
        messages.append({"role": "user", "content": user_message})

        # num_predict caps the OUTPUT length (tokens to generate).
        # Keep this low on CPU — 512 tokens ≈ 350-400 words, plenty for health answers.
        # num_ctx caps the INPUT context window processed during prefill.
        # Default is 32k+ on Qwen3 which is very slow on CPU; 4096 covers our prompts.
        num_predict = 768 if query_type == "risk_analysis" else 512

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,  # streaming requires router-level changes (StreamingResponse)
            "options": {
                "num_predict": num_predict,
                "num_ctx": 4096,
            },
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