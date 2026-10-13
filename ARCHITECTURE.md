# Architecture

The single description of how the system is built and which rules it must keep.
For features, setup and usage see [README.md](README.md); for known limitations
see [README › Known Limitations and Design Decisions](README.md#known-limitations-and-design-decisions).

Every statement below cites the code that supports it (`file:line`, paths
relative to the repository root).

---

## Components

Five Docker Compose services (`docker-compose.yml:3-76`):

| Service | Role | Evidence |
|---|---|---|
| `postgres` | PostgreSQL 16 with the pgvector extension | `docker-compose.yml:4` |
| `ollama` | Local LLM and embedding server | `docker-compose.yml:19-20` |
| `ollama-pull` | One-shot job that pulls the chat model and `nomic-embed-text` | `docker-compose.yml:44-45` |
| `backend` | FastAPI app on port 8000; talks to `postgres` and `ollama` | `docker-compose.yml:48-68` |
| `frontend` | Streamlit multi-page UI on port 8501; talks only to `backend` | `docker-compose.yml:70-76` |

### Backend modules

- **Routers** (`backend/main.py:42-50`): `/upload`, `/chat`, `/bp`,
  `/family-history`, `/dashboard`, `/recommendations`.
- **Ingestion** (`backend/ingestion/`): PDF lab parser, lab-name normaliser,
  unit converter, Samsung Health parser.
- **Services** (`backend/services/`): LLM client, RAG (embeddings + vector
  search), risk engine (Framingham, FINDRISC, AHA blood pressure), risk-score
  persistence, screening rules, MedlinePlus client.

Models: chat model from `settings.ollama_model` (default `llama3.2:3b`) and
embedding model `nomic-embed-text` (`backend/config.py:10-11`), both served by
Ollama over HTTP (`backend/services/llm_service.py:172`,
`backend/services/rag_service.py:34`).

---

## Data flows

### Lab PDF upload — `POST /upload/pdf`
1. The PDF is saved to `settings.upload_dir` under a generated
   `timestamp_uuid` name; the original filename is not persisted
   (`backend/routers/upload.py:43-53`).
2. `PDFParser` extracts values with pdfplumber and regular expressions; lab
   names are normalised by `LabNormalizer` inside the parser
   (`backend/ingestion/pdf_parser.py:203,417,464`). No LLM is involved.
3. Each value is stored as a `LabResult` row and embedded as `lab_result`
   (`backend/routers/upload.py:77-96`). Parse warnings are returned to the
   caller (`backend/routers/upload.py:108`).

### Wearable upload — `POST /upload/samsung`
Daily summaries are upserted into `samsung_health_metrics`, keyed on
`(metric_type, recorded_at)` (`backend/routers/upload.py:112-197`). A Samsung
upload also stores one `samsung_summary` embedding
(`backend/routers/upload.py:197`). Rows written by the former Zepp Life
import (metric types such as `resting_hr`, `sleep_total_min`, `avg_spo2`,
`avg_stress`) remain in the table; the import itself has been removed.

### Blood pressure — `POST /bp/`
The reading is stored, classified per AHA 2017 and a `bp_classification`
row is written to `risk_scores` (`backend/routers/blood_pressure.py:83-96`).

### Family history — `POST /family-history/`
The entry is stored, embedded as `family_history`, then looked up on
MedlinePlus to warm the cache (`backend/routers/family_history.py:55-67`).

### Chat — `POST /chat/`
1. Language detection and keyword intent detection
   (`backend/routers/chat.py:693,696`).
2. SQL context builders run only for the detected intents: date-specific,
   wearable metrics, lab trends, blood pressure, family history, risk scores
   (`backend/routers/chat.py:705-734`).
3. Risk scores: baseline scores are computed and persisted by
   `compute_baseline_scores`; hypothetical ("what if") scores are computed in
   memory (`backend/routers/chat.py:535,542-664`).
4. RAG: the message is embedded and the five nearest `embeddings` rows above
   the similarity threshold are retrieved, with no source-type filter
   (`backend/services/rag_service.py:167`, threshold `backend/config.py:17`).
5. Everything is formatted into the system prompt and sent to Ollama
   `/api/chat` (`backend/routers/chat.py:744`,
   `backend/services/llm_service.py:172`). The response never cites sources
   (`backend/routers/chat.py:759`).

### Recommendations — `GET /recommendations/`
Baseline risk scores are computed and persisted, then hard-coded
`SCREENING_RULES` are matched against age, sex, family history and flagged labs;
each matched condition is looked up on MedlinePlus for a summary and link
(`backend/routers/recommendations.py:36-55`,
`backend/services/screening_service.py:44,161,196`).

### Dashboard — `GET /dashboard/summary`
Reads lab results and the five latest `risk_scores` rows
(`backend/routers/dashboard.py:25,45`).

---

## Data stores

- **PostgreSQL tables** (`backend/models/db_models.py`): `user_profile` (:20),
  `lab_results` (:41), `blood_pressure_readings` (:59), `family_history` (:75),
  `samsung_health_metrics` (:91), `embeddings` (:109), `medlineplus_cache`
  (:123), `risk_scores` (:136).
- **Schema creation**: at startup, `CREATE EXTENSION IF NOT EXISTS vector` and
  `create_all` (`backend/database/connection.py:31-32`). Alembic is configured
  but `backend/database/migrations/versions/` holds no migrations.
- **Vector store**: `embeddings.embedding` is `Vector(768)`
  (`backend/models/db_models.py:119`). Only three source types are written:
  `lab_result` (`backend/routers/upload.py:96`), `samsung_summary`
  (`backend/routers/upload.py:197`), `family_history`
  (`backend/routers/family_history.py:58`). No medical literature or guideline
  text is embedded.
- **Files**: uploaded PDFs are kept on disk in `settings.upload_dir`
  (`backend/config.py:13`), mounted from `./data/uploads` in Compose
  (`docker-compose.yml:68`).

---

## External calls

| Call | From | What is sent | Evidence |
|---|---|---|---|
| Ollama (local container) | backend | Prompts and texts to embed; stays on the host | `backend/services/llm_service.py:172`, `backend/services/rag_service.py:34` |
| MedlinePlus Web Service | backend | A topic search term | `backend/config.py:14`, `backend/services/medlineplus_service.py:100-104` |
| MedlinePlus Connect | backend | An ICD-10 code | `backend/config.py:15`, `backend/services/medlineplus_service.py:136-144` |

Streamlit usage statistics from the frontend are disabled
(`frontend/.streamlit/config.toml:7`).

MedlinePlus calls are rate-limited and cached for `medlineplus_cache_ttl_days`
(`backend/services/medlineplus_service.py:22-66,221-275`).

---

## Invariants

A change that could break an invariant in list (a) needs explicit approval
before it is made (see [AGENTS.md](AGENTS.md)).

### (a) Enforced today

1. **Lab units are never guessed; an unrecognised or missing unit yields no
   score, not a wrong one.**
   Stored lab values are converted only from mg/dL or mmol/L; anything else
   returns `None` with a warning (`backend/ingestion/unit_converter.py:50-70`).
   Missing inputs skip the score with no defaults substituted
   (`backend/services/risk_score_service.py:73-96,131-147`); the hypothetical
   fallback uses the same converter (`backend/routers/chat.py:498-503`).
   Exception: cholesterol values typed into a "what if" question carry no unit
   and are read as mg/dL (`backend/routers/chat.py:595-604`); values in the
   mmol/L range are rejected by the plausibility guard
   (`backend/services/risk_engine.py:149-160`), the error is logged and no
   hypothetical score is shown (`backend/routers/chat.py:662-663`).

2. **Hypothetical ("what if") recalculations are never persisted.**
   The hypothetical branch only reads from the database
   (`backend/routers/chat.py:489,508,518`) and returns its results in memory
   (`backend/routers/chat.py:542-664`); only baseline scores are persisted, via
   `compute_baseline_scores` (`backend/routers/chat.py:535`,
   `backend/services/risk_score_service.py:306-336`). No test asserts this yet.

3. **Retrieved data is wrapped in tagged blocks and the prompt instructs the
   model never to treat it as instructions.**
   Tags: `backend/services/llm_service.py:32-58`; rule:
   `backend/services/llm_service.py:61`; template tests:
   `backend/tests/test_llm_service.py`. Whether the model obeys cannot be
   enforced in code. Known exception: `conversation_history` is forwarded to
   the model verbatim from the client, roles unchecked
   (`backend/models/api_models.py:111`, `backend/services/llm_service.py:157`).

4. **The backend's only external call is MedlinePlus; it receives condition
   or topic terms only:**
   - the ICD-10 code the user entered for a family-history entry
     (`backend/routers/family_history.py:63`);
   - the user's free-text family-history condition, verbatim, when no ICD-10
     code is given (`backend/routers/family_history.py:65`);
   - screening condition names from the hard-coded `SCREENING_RULES`
     (`backend/services/screening_service.py:44,196`). Which names are sent
     depends on the user's age, sex, family history and flagged labs, so the
     set of queries indirectly reflects that profile.

5. **The user's own records are never presented as an external source.**
   The prompt labels retrieved context as "semantic search over stored health
   records" from "the user's own records"
   (`backend/services/llm_service.py:55,61`); chat responses cite no sources
   (`backend/routers/chat.py:759`). Known exception: when retrieval fails, the
   fallback text placed in the context reads "Medical knowledge retrieval
   unavailable" (`backend/routers/chat.py:740`).

6. **No usage telemetry leaves the host.**
   Streamlit's `browser.gatherUsageStats` defaults to `true`; it is set to
   `false` in `frontend/.streamlit/config.toml:7`, which the frontend image
   copies into its working directory (`frontend/Dockerfile:3,13,19`).

7. **Services are reachable only from the host.**
   Every published port is bound to `127.0.0.1` (`docker-compose.yml:12,24,65,77`);
   services reach each other over the Compose network by service name. The
   API has no authentication, so this binding is what keeps other machines
   on the network away from the data.

### (b) Targets — NOT yet implemented

- **Target:** if requested data does not exist, the assistant says so instead
  of answering. Today only default placeholder strings are passed
  (`backend/services/llm_service.py:145-146`); nothing prevents an answer.
- **Target:** the LLM runs only when needed. Today every chat message calls the
  LLM (`backend/routers/chat.py:744`).
- **Target:** MedlinePlus content is used in chat answers. Today MedlinePlus
  results are only displayed on the recommendations page and never reach the
  prompt.
- **Target:** risk scores that cannot be computed correctly are not shown.
  Today the female Framingham table is a copy of the male table
  (`backend/services/risk_engine.py:107-114`) and the score is shown anyway.
