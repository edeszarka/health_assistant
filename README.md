# 🏥 Health Assistant

[![CI](https://github.com/edeszarka/health_assistant/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/edeszarka/health_assistant/actions/workflows/ci.yml)

> **A local-first personal health intelligence assistant powered by Qwen2.5 (via Ollama), PostgreSQL/pgvector, and Streamlit.**

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
│                       │  qwen2.5:3b    │      │  (Auto-setup)  │   │
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

- 📂 **Lab PDF Import** – Upload lab PDFs in two Hungarian report layouts, with Hungarian, Latin or English test names; a deterministic pdfplumber + regex parser extracts values for dictionary-based normalisation, and any parsing warnings are surfaced in the UI
- 💉 **Blood Pressure Tracker** – Log readings; auto-classified per AHA 2017 guidelines
- 🧬 **Family History** – Record hereditary conditions with ICD-10 codes
- 📱 **Samsung Health Import** – ZIP parser for steps, distance, active calories, sleep, heart rate, weight and BMI; finds the files in subfolders of the export. One value is kept per metric per day (the last row read, not a sum or average). Re-importing updates those daily rows instead of duplicating them, but each upload adds another summary embedding. Parse failures are logged as warnings.
- 🤖 **AI Health Chat** – Conversation over your own data: keyword matching selects records from SQL, and semantic search (RAG) adds at most one more; responds in the user's language (HU/EN)
- 📊 **Dashboard** – Flagged labs, BP trends, risk scores at a glance
- 📋 **Screening Recommendations** – Personalised USPSTF-based checklist with MedlinePlus links
- 🎯 **Risk Scores** – Framingham 10-year CHD risk (men aged 20-79 without diabetes), FINDRISC diabetes risk
- 🔒 **Privacy-first** – Your health records stay local; at run time the app calls only MedlinePlus (NIH public API) externally, with lookup terms only, and `docker compose up` contacts the Ollama registry for the models (see [Data Privacy](#data-privacy))

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
# This will automatically pull the AI models (qwen2.5:3b, nomic-embed-text)
docker compose up -d

# 4. Open the app
# (On first run the backend starts only after the models have downloaded,
# which can take a while depending on your connection)
start http://localhost:8501   # Frontend (Windows)
# open http://localhost:8501  # macOS/Linux
```

API docs available at: **http://localhost:8000/docs**

---

## How to Use

### Upload a Lab PDF
1. Go to **📂 Upload** in the sidebar
2. Select the "Lab PDF" tab
3. Upload your PDF (EESZT or legacy/Corden layout; test names can be Hungarian, Latin or English)
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
3. Keyword matching decides which of your data goes into the prompt: lab values,
   the latest blood pressure with an average, family history, wearable metrics.
   A question that matches no keyword gets all of them, and semantic search
   adds at most one stored record
4. For lab and family-history questions it also gets MedlinePlus text (what a
   test measures, what a condition is); the MedlinePlus pages used are listed
   under the answer as sources
5. The prompt asks the model to end health advice with a reminder to consult
   your doctor. Nothing enforces this: in the 2026-11-02 answer eval,
   `qwen2.5:3b` did so in 31 of 48 English and 0 of 12 Hungarian answers (plain
   value lookups included), and replies produced without the LLM do not add it

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
2. See a personalized checklist of health screenings based on your profile and
   data. Without a stored profile, age 40 is assumed and sex-specific rules are
   left out. Family-history triggers look for English words in the condition you
   typed (`diabetes`, `heart attack`), so "cukorbetegség" does not trigger one;
   lab triggers count every flagged result on record, also old ones
3. Each item shows the reason, the suggested specialist and, when found, the
   MedlinePlus summary and a link button. The tick boxes are not saved

### Import Samsung Health Data
1. Go to **📂 Upload**
2. Select the "Samsung Health" tab
3. Upload your ZIP export
4. Click **Process Samsung Data**

---

## Data Privacy

| What | Status |
|---|---|
| Lab results | ✅ Stored only locally: in PostgreSQL, and the uploaded PDF in `data/uploads/` |
| Blood pressure | ✅ Stored only in your local PostgreSQL |
| Family history | ✅ Stored only in your local PostgreSQL |
| AI inference | ✅ Runs entirely on Ollama (local) |
| Model download | ⚠️ On `docker compose up`, the `ollama-pull` job contacts the Ollama registry for the two models. No health data is sent |
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
| ORM | SQLAlchemy 2.0 (async); tables created at startup with `create_all` (Alembic is configured, but there are no migrations yet) |
| LLM | Ollama — qwen2.5:3b |
| Embeddings | Ollama — nomic-embed-text (768d) |
| Orchestration | None — direct Ollama REST calls via httpx |
| Parsing | pdfplumber |
| External API | MedlinePlus Web Service and MedlinePlus Connect (NIH, no key) |
| Testing | pytest, pytest-asyncio, httpx |
| Containers | Docker + Docker Compose |

---

## AI Design and Evaluation
**LLM — qwen2.5:3b**: Chosen on 2026-10-19 with the answer evaluation below,
from three models that run on a CPU-only laptop (Ryzen 5 PRO 4650U, 16 GB RAM),
English answers deciding. Results of the re-run on 2026-11-02, with the raw output
in [`backend/eval/results`](backend/eval/results/README.md):

| Model | English answers passed | English answers with a number not in the prompt | Hungarian answers passed |
|---|---|---|---|
| **qwen2.5:3b** | **44 of 48** | 2 of 48 | 7 of 12 |
| llama3.2:3b | 44 of 48 | 4 of 48 | 5 of 12 |
| qwen2.5:1.5b | 38 of 48 | 7 of 48 | 4 of 12 |

Reply times were measured on 2026-10-19 with `--cold`, on the 16 English cases;
that output was not kept:

| Model | Median / p90 reply, cold¹ | Reading / writing speed |
|---|---|---|
| qwen2.5:3b | 64 s / 73 s | 23 / 5.8 tokens/s |
| qwen2.5:1.5b | 31 s / 42 s | 46 / 11 tokens/s |

¹ With `--cold`, no prompt prefix is reused from Ollama's cache. The eval's
fictional prompts are ~1100 tokens. A real lab question now carries in full only the
asked-about and flagged labs, plus the risk-score labs and rising trends when it
names no test, and lists other tests by name ([ADR 0012](docs/adr/0012-lab-context-asked-and-flagged.md)),
a ~1100–1300-token prompt, and took **73–81 s** live with `qwen2.5:3b` when not
cached (before: ~2500 tokens, 150 s). Long answers, or the first question after
Ollama unloaded the model, took 106–137 s. A follow-up whose prompt is cached
takes ~25–50 s.

The two 3B models tie on pass rate, and the difference in unsourced numbers is
within run-to-run variation: on 2026-10-19 `llama3.2:3b` had the fewer of them.
`qwen2.5:3b` was chosen because, in that earlier run, its failures were general
reference ranges quoted from memory, while `llama3.2:3b` invented a value for the
user and attributed unsourced ranges to MedlinePlus; see
[ADR 0010](docs/adr/0010-chat-model-choice.md). Hungarian answers are weak with
every candidate (7 of 12 at best). The `/no_think`
prefix asks the model to answer directly, without extended reasoning.

**Embedding — nomic-embed-text**: 768-dimensional embeddings via Ollama, 
entirely local. Selected over OpenAI text-embedding-3-small because no 
health data leaves the machine. Its retrieval quality on this app's data is
measured by the RAG evaluation below; no external benchmark is relied on.

**RAG Evaluation**: `python -m eval.retrieval_eval` (inside the backend
container) runs 20 Hungarian/English lab and family-history questions plus 5
off-topic ones against the live store. Relevance is judged by metadata (source
type and normalised test name), so no health values are printed. Measured on
2026-11-02 on 42 stored records, with the raw output in
[`backend/eval/results`](backend/eval/results/README.md): at the configured
operating point (top-1, similarity >= 0.62), 17 of 20 questions retrieve a relevant
record (Hungarian 7 of 10, English 10 of 10), the other 3 retrieve a wrong one, and
none of the 5 off-topic questions retrieves anything. At the same threshold, more
rows find at most 18 of 20, while only 32-50% of the rows are relevant. A lower
threshold lets off-topic questions through (1 of 5 at 0.60). The sample is small
and from one person's records, the point was chosen and reported on the same
questions, and a clean clone cannot reproduce the run.
Embedded texts carry the report's own Hungarian test names and nomic's
`search_document:`/`search_query:` prefixes; the commit that added this reports
Hungarian recall of at most 40% before it (`3d5177b`; that output was not kept).
After changing the embedding model or the text templates, run
`python -m scripts.reembed` and re-run the eval.

**Answer Evaluation**: `python -m eval.answer_eval --model <name>` (inside the
backend container) asks the chat model 16 English and 4 Hungarian questions
over fictional data (`backend/eval/answer_cases.json`) through the real system
prompt, and scores each answer with deterministic checks
(`backend/eval/answer_scoring.py`): the expected values are quoted, no number
appears that was not in the prompt (whole numbers up to 10 and years are not
checked), missing data is reported as missing, a prompt injection inside a data
block is not followed (one case), and the answer is in the question's language.
The cases supply hand-written context and the language, so language and intent
detection, the SQL context and retrieval are not part of this eval. It reports the pass rate per language and the median
latency. English cases decide the model choice; Hungarian ones are reported
for information. The checks are necessary, not sufficient: there is no LLM
judge, so a wrong claim built from correct numbers passes (seen with
`qwen2.5:1.5b`: "LDL 3.9 mmol/L is within the reference range of 0-3.0").
Answers vary between runs at the chat's sampling settings, so compare models
with `--repeat 3`. Use `--cold` for latency: without it, the shared
fictional context is served from Ollama's prompt cache and the times are
too low.

**Hungarian/Latin → Standard normalization**: Single-stage, dictionary-only.
A hardcoded lookup dictionary in `backend/ingestion/lab_normalizer.py`
(`KNOWN_MAPPINGS`) maps known Hungarian/Latin lab names to standard keys
(e.g., Fehérvérsejt → wbc, Karbamid → bun). `LabNormalizer.normalize()`
resolves each raw name in three steps: exact match, then longest substring
match against the dictionary, then a lowercase fallback of the raw name for
unmapped entries. No LLM is involved in this path.

## Development

> 💡 **Developer Tip**: Docker bind-mounts `backend/` into the backend container and runs uvicorn with `--reload`, so backend changes are reflected immediately without rebuilding. The frontend is baked into its image with no mount or reload, so frontend changes require `docker compose up -d --build frontend`.

### Run tests
```bash
# Inside the backend container (Recommended)
docker compose exec backend pytest tests/ -v

# Locally (requires the dependencies and both database URLs, which Settings needs)
cd backend
DATABASE_URL=postgresql+asyncpg://healthuser:pw@localhost:5432/healthassistant \
SYNC_DATABASE_URL=postgresql+psycopg2://healthuser:pw@localhost:5432/healthassistant \
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
The repository has no migrations yet: `create_all` creates missing tables when
the backend starts and does not change existing ones. A table the app has
already created therefore does not appear in an autogenerated migration. The
commands need `DATABASE_URL` and `SYNC_DATABASE_URL`, as above.
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
skipped result rows. The sample date is recognised only from a Hungarian "Mintavétel" line.
Without one the upload warns, and its rows are stored but left out of the chat's
lab block. Production would require a human review step for parsed
values.

**No human-in-the-loop for parsed data**: Automated parsing of medical values without
verification is a known risk. A decimal misread (5.5 vs 55 mmol/L) would affect risk scores.
Production health systems require a data-verification UI before persistence.

**CPU-only LLM**: On a CPU-only laptop, `qwen2.5:3b` reads the prompt at about
23 tokens/s and writes at about 6 tokens/s. A question with a small prompt
takes ~30 s; a lab question (~1100–1300-token prompt, narrowed lab block) takes about 75–80 s when the prompt is not cached, and up to
~140 s for a long answer or right after the model was unloaded.
Production deployment would require GPU inference or a hosted model endpoint.

**Embedding staleness**: Embeddings are created at upload time and not updated if source
data changes. Through the app, lab results and family history are added rather than edited,
which makes this acceptable; deleting a family-history entry also deletes its
embedding. Daily Samsung rows can be overwritten, but only an upload summary is
embedded, and lab values typed into the risk form are not embedded. Production
would require an embedding refresh pipeline.

**PII handling**: Uploaded lab PDFs are retained verbatim on disk under
`data/uploads/` on the host (`/app/uploads` in the container), and the `LabResult.source_filename` column stores only a generated
upload identifier (timestamp + UUID) — never the original filename, which could
embed the patient's name. The retained PDF itself can still contain the
patient's name and other identifiers in plaintext, so production deployment
would require field-level encryption and a clear data retention policy.

**Lab units are explicit, never guessed**: risk-score inputs from Hungarian lab
PDFs are converted to mg/dL only when the stored unit is recognised. Conversion
is supported for total cholesterol, LDL, HDL, triglycerides and glucose. A value
with a missing or unrecognised unit is skipped rather than assumed, so a risk
score may be unavailable instead of wrong. Exception: a cholesterol value typed
into a "what if" question has no unit and is read as mg/dL; a value in the mmol/L
range fails the plausibility check, and no hypothetical score is shown.

**Framingham covers men aged 20-79 without diabetes**: the score uses the NCEP
ATP III point table for men. No score is shown or saved for women, because no
women's table is implemented; for diagnosed diabetes, which ATP III treats as a
coronary heart disease risk equivalent rather than a point item; or outside ages
20-79. The reply gives the reason instead. FINDRISC is unaffected. See
[ADR 0013](docs/adr/0013-framingham-atp3-male-only.md). Framingham is tested
against the published ATP III point table
(`backend/tests/test_risk_published_tables.py`). FINDRISC uses the 26-point
questionnaire; its tests fix the point values and bands, but they have not been
compared with that questionnaire's primary source.

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
prompts with the Qwen2.5 tokenizer), so another model family may need a new
measurement. Error
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
