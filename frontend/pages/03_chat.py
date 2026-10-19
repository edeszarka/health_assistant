import os
import httpx
import streamlit as st

from risk_form import render_risk_form

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Chat", page_icon="💬", layout="wide")
st.title("💬 Chat with Your Health AI")
st.caption("Ask anything about your lab results, blood pressure, or family history.")

if "messages" not in st.session_state:
    st.session_state.messages = []
# Open risk-input form: {"status": ..., "language": ...} or None
if "risk_request" not in st.session_state:
    st.session_state.risk_request = None

# Render existing messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Risk-input form below the reply that asked for it
if st.session_state.risk_request:
    result_message = render_risk_form(BACKEND, st.session_state.risk_request)
    if result_message:
        st.session_state.messages.append(
            {"role": "assistant", "content": result_message, "source": "automatic"}
        )
        st.session_state.risk_request = None
        st.rerun()

# User input
if prompt := st.chat_input("Type your question… (Hungarian or English)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build history excluding latest message. "source" tells the backend which
    # assistant turns the model did not write: errors are dropped, automatic
    # replies are marked (backend/services/chat_history.py).
    history = [
        {"role": m["role"], "content": m["content"], "source": m.get("source", "llm")}
        for m in st.session_state.messages[:-1]
    ]

    data_request = None
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                with httpx.Client(timeout=1800.0) as client:
                    resp = client.post(
                        f"{BACKEND}/chat/",
                        json={"message": prompt, "conversation_history": history},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("reply", "Sorry, I could not generate a response.")
                    sources = data.get("sources", [])
                    reply_source = data.get("source", "llm")
                    if data.get("data_request"):
                        data_request = {
                            "status": data["data_request"],
                            "language": data.get("language", "English"),
                        }
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", e.response.text)
                except Exception:
                    detail = e.response.text
                reply = f"❌ Backend error: {detail}"
                sources = []
                reply_source = "error"
            except Exception as e:
                reply = f"❌ Backend error: {e}"
                sources = []
                reply_source = "error"

        st.markdown(reply)
        if sources:
            st.caption(f"Sources: {', '.join(sources)}")

    st.session_state.messages.append(
        {"role": "assistant", "content": reply, "source": reply_source}
    )
    # A new question closes an open form; a risk request opens a fresh one.
    st.session_state.risk_request = data_request
    if data_request:
        st.rerun()
