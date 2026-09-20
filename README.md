# 🏥 Health Assistant

[![CI](https://github.com/edeszarka/health_assistant/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/edeszarka/health_assistant/actions/workflows/ci.yml)

> **A local-first personal health intelligence assistant powered by Llama 3.2, PostgreSQL/pgvector, and Streamlit.**

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
│                       ┌────────────────┐      ┌────────────────┐   │
│                       │  Ollama        │◀─────│  Ollama-Pull   │   │
│                       │  llama3.2:3b   │      │  (Auto-setup)  │   │
│                       │  nomic-embed   │      └────────────────┘   │
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

- 📂 **Lab PDF Import** – Upload medical PDFs (Hungarian/Latin/English); a deterministic pdfplumber + regex parser extracts values for dictionary-based normalisation, and any parsing warnings are surfaced in the UI
- 💉 **Blood Pressure Tracker** – Log readings; auto-classified per AHA 2017 guidelines
- 🧬 **Family History** – Record hereditary conditions with ICD-10 codes
- 📱 **Samsung Health Import** – Robust ZIP parser for steps, sleep, heart rate, and body metrics; handles subfolder exports, prevents duplicates, and includes detailed logging for troubleshooting.
- ⌚ **Zepp Life Import** – Support for Zepp Life ZIP data (includes AES-encrypted file support)
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
# This will automatically pull the AI models (llama3.2:3b, nomic-embed-text)
docker-compose up -d

# 4. Open the app
# (Wait a minute on first run for models to download)
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
4. Click **Process PDF** — values are parsed and normalised automatically (no LLM involved); any parsing warnings appear below the result

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

### View Recommendations
1. Go to **📋 Recommendations**
2. See a personalized checklist of health screenings based on your profile and data
3. Click on conditions to see detailed info from MedlinePlus

### Import Samsung or Zepp Life Data
1. Go to **📂 Upload**
2. Select the "Samsung Health" or "Zepp Life" tab
3. Upload your ZIP export
4. For Zepp Life, enter the export password if requested

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
| Frontend | Streamlit, Pandas, Plotly |
| Database | PostgreSQL 16 + pgvector extension |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| LLM | Ollama — llama3.2:3b |
| Embeddings | Ollama — nomic-embed-text (768d) |
| Orchestration | None — direct Ollama REST calls via httpx |
| Parsing | pdfplumber, pyzipper |
| External API | MedlinePlus Web Service (NIH, no key) |
| Testing | pytest, pytest-asyncio, httpx |
| Containers | Docker + Docker Compose |

---

## AI Design and Evaluation
**LLM — llama3.2:3b**: Selected for its exceptional balance of speed and reasoning
on consumer-grade CPUs. At 3B parameters, it provides highly responsive 
conversational performance (typically 15-40s per response on modern CPUs) 
while maintaining the multilingual capability required for Hungarian/English 
medical terminology. The `/no_think` prefix is used to prioritize immediate 
answer generation over extended chain-of-thought reasoning.

**Embedding — nomic-embed-text**: 768-dimensional embeddings via Ollama, 
entirely local. Selected over OpenAI text-embedding-3-small because no 
health data leaves the machine. Benchmarks show competitive retrieval 
quality on domain-specific text at this dimension size.

**RAG Evaluation**: Manually validated against 3 uploaded lab reports 
(46, 38, and 51 results each). Retrieval precision tested by asking 
10 questions per report and verifying the correct lab values appeared 
in the LLM context before answering. Known failure mode: cosine 
similarity threshold of 0.75 occasionally misses results with 
domain-specific Hungarian terminology not well-represented in the 
embedding space. A production system would use RAGAS or a similar 
automated evaluation framework.

**Hungarian/Latin → Standard normalization**: Single-stage, dictionary-only.
A hardcoded lookup dictionary in `backend/ingestion/lab_normalizer.py`
(`KNOWN_MAPPINGS`) maps known Hungarian/Latin lab names to standard keys
(e.g., Fehérvérsejt → wbc, Karbamid → bun). `LabNormalizer.normalize()`
resolves each raw name in three steps: exact match, then longest substring
match against the dictionary, then a lowercase fallback of the raw name for
unmapped entries. No LLM is involved in this path.

## Development

> 💡 **Developer Tip**: Docker bind-mounts `backend/` into the backend container and runs uvicorn with `--reload`, so backend changes are reflected immediately without rebuilding. The frontend is baked into its image with no mount or reload, so frontend changes require `docker-compose up -d --build frontend`.

### Run tests
```bash
# Inside the backend container (Recommended)
docker exec health_assistant-backend-1 pytest tests/ -v

# Locally (requires dependencies)
cd backend
pytest tests/ -v
```

### Run backend locally (without Docker)
```bash
cd backend
DATABASE_URL=postgresql+asyncpg://... SYNC_DATABASE_URL=postgresql+psycopg2://... OLLAMA_BASE_URL=http://localhost:11434 uvicorn main:app --reload
```

### Add a new lab normalisation mapping
Edit `backend/ingestion/lab_normalizer.py` → add to `KNOWN_MAPPINGS`:
```python
"your raw name": "standard_key",
```

### Add a new lab unit conversion
Edit `backend/ingestion/unit_converter.py` → add the mmol/L → mg/dL factor to
`MOLAR_MASS_FACTORS` (document the molar-mass source next to it):
```python
"your_test_name": 12.34,  # source: molar mass / conversion table
```

### Generate a new Alembic migration
```bash
cd backend
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### Add a new screening rule
Edit `backend/services/screening_service.py` → add a `ScreeningRule` to `SCREENING_RULES`:
```python
ScreeningRule("Test Name", min_age, max_age, sex_filter=..., family_trigger=..., lab_trigger=..., urgency="...", specialist="..."),
```

`family_trigger` and `lab_trigger` are alternative (OR) activation paths: a rule
with neither always applies within its age/sex range, while a rule with either
fires when at least one trigger matches.

## Known Limitations and Design Decisions

**Single-user, local-only**: Deliberately designed for personal use on a local machine.
No data leaves the host. Multi-tenancy would require auth and user_id FKs on all tables.

**PDF parsing brittleness**: Two real-world layouts are supported — the EESZT
numbered/LOINC tabular format and the legacy/Corden format — including colon-less
rows, comma/dot decimals, `magas`/`alacsony`/`*` flags, and open-ended ranges.
Dictionary-based normalization covers known Hungarian/Latin names, but
provider-specific abbreviations and further layout variants remain a known failure
mode. Rows that cannot be parsed (qualitative or inequality-bounded results, e.g.
eGFR reported as ">90") are silently skipped — today only document-level issues
(missing or malformed sample date) are reported via the upload `warnings` list, not
individual skipped rows. Production would require a human review step for parsed
values.

**No human-in-the-loop for parsed data**: Automated parsing of medical values without
verification is a known risk. A decimal misread (5.5 vs 55 mmol/L) would affect risk scores.
Production health systems require a data-verification UI before persistence.

**CPU-only LLM**: Response times of 30–90 seconds are acceptable for personal use.
Production deployment would require GPU inference or a hosted model endpoint.

**Embedding staleness**: Embeddings are created at upload time and not updated if source
data changes. For append-only health data this is acceptable; production would require
an embedding refresh pipeline.

**PII handling**: Uploaded lab PDFs are retained verbatim on disk under
`uploads/`, and the `LabResult.source_filename` column stores only a generated
upload identifier (timestamp + UUID) — never the original filename, which could
embed the patient's name. The retained PDF itself can still contain the
patient's name and other identifiers in plaintext, so production deployment
would require field-level encryption and a clear data retention policy.

**Lab units are explicit, never guessed**: risk-score inputs from Hungarian lab
PDFs are converted to mg/dL only when the stored unit is recognised. Conversion
is supported for total cholesterol, LDL, HDL, triglycerides and glucose. A value
with a missing or unrecognised unit is skipped rather than assumed, so a risk
score may be unavailable instead of wrong.

**Female Framingham table is a placeholder**: `_FRAMINGHAM_RISK_FEMALE` in
`backend/services/risk_engine.py` is currently a copy of the male
points-to-risk table. It must be replaced with the published Wilson et al. 1998
women's table before the female 10-year score can be trusted.

**FINDRISC activity is assumed**: the calculator still assumes 30 minutes of
daily physical activity instead of deriving it from the stored wearable step
data, which can over- or under-state the diabetes risk score.

## Roadmap (Planned / Not yet implemented)

- **LLM-assisted lab-name normalization**: fall back to the local LLM for raw
  lab names not found in `KNOWN_MAPPINGS` (provider-specific abbreviations,
  Latin variants). Not implemented today — normalization is dictionary-only.
