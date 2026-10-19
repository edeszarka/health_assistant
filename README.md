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
                                ▼ (lookup terms only, no records)
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
- 🤖 **AI Health Chat** – RAG-augmented conversation using your actual data; responds in the user's language (HU/EN)
- 📊 **Dashboard** – Flagged labs, BP trends, risk scores at a glance
- 📋 **Screening Recommendations** – Personalised USPSTF-based checklist with MedlinePlus links
- 🎯 **Risk Scores** – Framingham 10-year CV risk, FINDRISC diabetes risk
- 🔒 **Privacy-first** – Your health records stay local; only MedlinePlus (NIH public API) is called externally, with lookup terms only (see [Data Privacy](#data-privacy))

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
4. With an ICD-10 code (e.g. `E11`), the entry shows the MedlinePlus summary
   and link, and the chat uses that text for family-history questions; only
   the code is sent to MedlinePlus, once, when you save the entry

### Chat with the AI
1. Go to **💬 Chat**
2. Ask anything in **Hungarian or English** — the AI responds in kind
3. The assistant uses your actual lab values, BP history, and family history
4. For lab and family-history questions it also gets MedlinePlus text (what a
   test measures, what a condition is); the MedlinePlus pages used are listed
   under the answer as sources
5. All responses end with a reminder to consult your doctor

To enable the MedlinePlus lab texts, fill the cache once (51 requests to NLM,
the same fixed list of lab-test codes for everyone; rerun now and then to
refresh):

```bash
docker compose exec -w /app backend python -m scripts.warm_medlineplus          # dry run
docker compose exec -w /app backend python -m scripts.warm_medlineplus --apply
```

### Calculate Your Risk Scores (FINDRISC, Framingham)
1. In **💬 Chat**, ask for your risk, e.g. "Mekkora a cukorbetegség kockázatom?"
   or "What is my cardiovascular risk?"
2. The reply lists what is stored (value and date, or "no data"), without
   calling the LLM, and a form opens below it, prefilled with the stored values
3. Fill in the profile once (birth year and month, sex, height, the FINDRISC
   and Framingham questions) and enter fresh weight, waist, blood pressure or
   cholesterol (with its unit) if you have them
4. **Save and calculate** stores the values and the scores; **Calculate with
   stored data** uses what is already stored. "What if" questions ("Ha 80 kg
   lennék…") are recalculated in memory and never saved

### View Recommendations
1. Go to **📋 Recommendations**
2. See a personalized checklist of health screenings based on your profile and data
3. Click on conditions to see detailed info from MedlinePlus

### Import Samsung Health Data
1. Go to **📂 Upload**
2. Select the "Samsung Health" tab
3. Upload your ZIP export

---

## Data Privacy

| What | Status |
|---|---|
| Lab results | ✅ Stored only in your local PostgreSQL |
| Blood pressure | ✅ Stored only in your local PostgreSQL |
| Family history | ✅ Stored only in your local PostgreSQL |
| AI inference | ✅ Runs entirely on Ollama (local) |
| MedlinePlus queries | ⚠️ Lookup terms only: screening condition names, the ICD-10 codes you enter for family history (free-text conditions are never sent), and a fixed list of lab-test codes that is the same for every user. Chat questions send nothing to MedlinePlus. No names, lab values or other records are sent, but the set of lookups can indirectly reflect your profile. Details: [ARCHITECTURE.md › External calls](ARCHITECTURE.md#external-calls) |
| `/data/` folder | 🚫 In `.gitignore` — never committed |
| `.env` file | 🚫 In `.gitignore` — never committed |

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI 0.110+, Python 3.12, Pydantic v2 |
| Frontend | Streamlit, Pandas |
| Database | PostgreSQL 16 + pgvector extension |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| LLM | Ollama — llama3.2:3b |
| Embeddings | Ollama — nomic-embed-text (768d) |
| Orchestration | None — direct Ollama REST calls via httpx |
| Parsing | pdfplumber |
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

**RAG Evaluation**: `python -m eval.retrieval_eval` (inside the backend
container) runs 20 Hungarian/English lab and family-history questions plus 5
off-topic ones against the live store. Relevance is judged by metadata (source
type and normalised test name), so no health values are printed. Measured
2026-10-17 on 42 stored records (after removing parser header rows and
duplicate uploads): the configured operating point (top-1, similarity >= 0.62)
reaches recall 85% (Hungarian 70%, English 100%) at 85% precision, and none of
the 5 off-topic questions retrieves a record. Retrieving more rows raises recall
to at most 90% while precision drops to 32-50%.
Embedded texts carry the report's own Hungarian test names and nomic's
`search_document:`/`search_query:` prefixes; before these changes Hungarian
recall was at most 40%. After changing the embedding model or the text
templates, run `python -m scripts.reembed` and re-run the eval.

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

The reasoning behind the main design decisions, with the alternatives that
were considered, is recorded in [docs/adr](docs/adr/README.md).

**Single-user, local-only**: Deliberately designed for personal use on a local machine.
No health records leave the host; only MedlinePlus lookup terms do (see [Data Privacy](#data-privacy)). Multi-tenancy would require auth and user_id FKs on all tables.

**PDF parsing brittleness**: Two real-world layouts are supported — the EESZT
numbered/LOINC tabular format and the legacy/Corden format — including colon-less
rows, comma/dot decimals, `magas`/`alacsony`/`*` flags, and open-ended ranges.
Dictionary-based normalization covers known Hungarian/Latin names, but
provider-specific abbreviations and further layout variants remain a known failure
mode. Rows that cannot be parsed (qualitative or inequality-bounded results, e.g.
eGFR reported as ">90") are silently skipped — the upload `warnings` list reports
document-level issues (missing or malformed sample date) and the number of dropped
header-like rows (patient/document fields repeated on later pages), not individual
skipped result rows. Production would require a human review step for parsed
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
points-to-risk table. Until it is replaced with the published Wilson et al. 1998
women's table, no Framingham score is shown or saved for women (FINDRISC is
unaffected).

**Risk scores need a complete profile**: FINDRISC and Framingham run only when
every input is stored (profile answers from the chat risk form, a weight and
waist measurement, and for Framingham cholesterol, HDL and a systolic BP). A
missing input skips the score instead of counting as 0 points, so a score may be
unavailable instead of too low. Physical activity is the user's yes/no answer to
the FINDRISC question, not derived from wearable step data. Age comes from the
birth year and month, so it can be up to one month early.

**Risk questions open the input form, not the LLM**: any chat message with a
risk keyword (`risk`, `kockázat`, `rizik`, `findrisc`, `framingham`, …) that is
not a "what if" question gets the stored-input list and the form, without an LLM
answer. This also applies to follow-ups such as "mit jelent a kockázatom?"; to
ask the LLM about a result, phrase the question without these words. The "what
if" check is a substring match, so "ha " also matches inside words such as
"néha", and such a question goes to the LLM instead of the form.

**The risk form saves in two calls**: the profile and measurements are saved
first (`PUT /risk/inputs`), then a new blood pressure reading (`POST /bp/`). If
the second call fails, the first is kept and an error is shown. Stale values
are marked in the chat reply, not in the form's captions.

**Long chats forget their oldest turns**: the model gets the system prompt
(about 2.3-3k tokens), the question and as many recent turns as fit an
8192-token window with 512 tokens kept for the reply. Older turns are dropped
for the model but still shown in the chat, without a notice. Token counts are
estimated from characters (2.5 characters per token, measured on this app's
prompts with qwen2.5:1.5b), so another model may need a new measurement. Error
messages shown in the chat are never sent back to the model.

**MedlinePlus text is English and cached**: MedlinePlus offers English (and
Spanish) only, so the model paraphrases the reference text in Hungarian; a small
model may do this imperfectly, and the source link points to the original. The
chat uses cached text only, also after it expires, until
`scripts.warm_medlineplus --apply` is rerun. A lab is matched in the question by
its name's start, so inflections that change the stem ("vércukrom" for
"vércukor") are missed; flagged labs still get their reference.

## Roadmap (Planned / Not yet implemented)

- **LLM-assisted lab-name normalization**: fall back to the local LLM for raw
  lab names not found in `KNOWN_MAPPINGS` (provider-specific abbreviations,
  Latin variants). Not implemented today — normalization is dictionary-only.
