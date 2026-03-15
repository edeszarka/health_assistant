import os
import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Chat", page_icon="💬", layout="wide")
st.title("💬 Chat with Your Health AI")
st.caption("Ask anything about your lab results, blood pressure, or family history.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Render existing messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User input
if prompt := st.chat_input("Type your question… (Hungarian or English)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build history excluding latest message
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
    ]

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                with httpx.Client(timeout=1200.0) as client:
                    resp = client.post(
                        f"{BACKEND}/chat/",
                        json={"message": prompt, "conversation_history": history},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("reply", "Sorry, I could not generate a response.")
                    sources = data.get("sources", [])
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", e.response.text)
                except Exception:
                    detail = e.response.text
                reply = f"❌ Backend error: {detail}"
                sources = []
            except Exception as e:
                reply = f"❌ Backend error: {e}"
                sources = []

        st.markdown(reply)
        if sources:
            st.caption(f"Sources: {', '.join(sources)}")

    st.session_state.messages.append({"role": "assistant", "content": reply})
