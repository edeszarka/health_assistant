# 🏥 Health Assistant

> **A local-first personal health intelligence assistant powered by Llama 3.1, PostgreSQL/pgvector, and Streamlit.**

> ⚠️ **Disclaimer**: This software is for **informational purposes only**. It does not constitute medical advice, diagnosis, or treatment. Always consult a qualified healthcare professional.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Docker Network                             │
│                                                                     │
│  ┌──────────────┐     ┌──────────────────┐     ┌────────────────┐  │
│  │  Streamlit   │────▶│  FastAPI Backend │────▶│  PostgreSQL 16 │  │
│  │  Frontend    │     │  (Python 3.12)   │     │  + pgvector    │  │
│  │  :8501       │     │  :8000           │     │  :5432         │  │
│  └──────────────┘     └────────┬─────────┘     └────────────────┘  │
│                                │                                    │
│                                ▼                                    │
│                       ┌────────────────┐                           │
│                       │  Ollama        │                           │
│                       │  llama3.1:8b   │                           │
│                       │  nomic-embed   │                           │
│                       │  :11434        │                           │
│                       └────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼ (no personal data sent)
                    ┌───────────────────────┐
                    │   MedlinePlus (NIH)   │
                    │   Public API          │
                    └───────────────────────┘
```

---

## Features

- 📂 **Lab PDF Import** – Upload medical PDFs (Hungarian/Latin/English); LLM extracts and normalises lab values
- 💉 **Blood Pressure Tracker** – Log readings; auto-classified per AHA 2017 guidelines
- 🧬 **Family History** – Record hereditary conditions with ICD-10 codes
- 📱 **Samsung Health Import** – Parse ZIP exports for steps, sleep, heart rate, and body metrics
- 🤖 **AI Health Chat** – RAG-augmented conversation using your actual data; responds in the user's language (HU/EN)
- 📊 **Dashboard** – Flagged labs, BP trends, risk scores at a glance
- 📋 **Screening Recommendations** – Personalised USPSTF-based checklist with MedlinePlus links
- 🎯 **Risk Scores** – Framingham 10-year CV risk, FINDRISC diabetes risk
- 🔒 **Privacy-first** – All data stays local; only MedlinePlus (NIH public API) is called externally

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker | 24+ | With Docker Compose v2 |
| Ollama | latest | Optional — handled by Docker |
| Git | any | For cloning |

---

## ⚡ Quick Start (5 commands)

```bash
# 1. Clone and enter the project
git clone <your-repo-url> health-assistant && cd health-assistant

# 2. Set your database password
cp .env.example .env
# Edit .env and set a secure POSTGRES_PASSWORD

# 3. Start everything
docker-compose up -d

# 4. Pull the AI models (first run only, ~5 GB)
docker-compose exec ollama ollama pull llama3.1:8b
docker-compose exec ollama ollama pull nomic-embed-text

# 5. Open the app
start http://localhost:8501   # Frontend (Windows)
# open http://localhost:8501  # macOS/Linux
```

API docs available at: **http://localhost:8000/docs**

---

## How to Use

### Upload a Lab PDF
1. Go to **📂 Upload** in the sidebar
2. Select the "Lab PDF" tab
3. Upload your PDF (supports Hungarian, Latin, or English medical terminology)
4. Click **Process PDF** — the AI extracts all values automatically

### Log Blood Pressure
1. Go to **💉 Blood Pressure**
2. Enter SYS / DIA / pulse and context (morning, evening, etc.)
3. Submit — the reading is classified instantly per AHA guidelines
4. View your 30-reading trend chart below

### Add Family History
1. Go to **🧬 Family History**
2. Select the relative, enter the condition and optional ICD-10 code
3. Submit — the entry is embedded in the vector database for AI context

### Chat with the AI
1. Go to **💬 Chat**
2. Ask anything in **Hungarian or English** — the AI responds in kind
3. The assistant uses your actual lab values, BP history, and family history
4. All responses end with a reminder to consult your doctor

---

## Data Privacy

| What | Status |
|---|---|
| Lab results | ✅ Stored only in your local PostgreSQL |
| Blood pressure | ✅ Stored only in your local PostgreSQL |
| Family history | ✅ Stored only in your local PostgreSQL |
| AI inference | ✅ Runs entirely on Ollama (local) |
| MedlinePlus queries | ⚠️ Condition names only, no personal data |
| `/data/` folder | 🚫 In `.gitignore` — never committed |
| `.env` file | 🚫 In `.gitignore` — never committed |

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI 0.110+, Python 3.12, Pydantic v2 |
| Frontend | Streamlit |
| Database | PostgreSQL 16 + pgvector extension |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| LLM | Ollama — llama3.1:8b |
| Embeddings | Ollama — nomic-embed-text (768d) |
| Orchestration | LangChain, langchain-ollama |
| PDF Parsing | pdfplumber |
| External API | MedlinePlus Web Service (NIH, no key) |
| Testing | pytest, pytest-asyncio, httpx |
| Containers | Docker + Docker Compose |

---

## Development

### Run tests
```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

### Run backend locally (without Docker)
```bash
cd backend
DATABASE_URL=postgresql+asyncpg://... OLLAMA_BASE_URL=http://localhost:11434 uvicorn main:app --reload
```

### Add a new lab normalisation mapping
Edit `backend/ingestion/lab_normalizer.py` → add to `KNOWN_MAPPINGS`:
```python
"your raw name": "standard_key",
```

### Generate a new Alembic migration
```bash
cd backend
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### Add a new screening rule
Edit `backend/services/screening_service.py` → add a tuple to `SCREENING_RULES`:
```python
("Test Name", min_age, max_age, sex_filter_or_None, family_trigger_or_None, urgency, specialist),
```
