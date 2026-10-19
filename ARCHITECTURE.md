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

- **Routers** (`backend/main.py:43-53`): `/upload`, `/chat`, `/bp`,
  `/family-history`, `/dashboard`, `/recommendations`, `/risk`.
- **Ingestion** (`backend/ingestion/`): PDF lab parser, lab-name normaliser,
  unit converter, Samsung Health parser.
- **Services** (`backend/services/`): LLM client, RAG (embeddings + vector
  search), risk engine (Framingham, FINDRISC, AHA blood pressure), risk inputs
  (read, status, save), risk-score persistence, screening rules, MedlinePlus
  client and reference selection (`medlineplus_context`, LOINC map
  `lab_loinc`).

Models: chat model from `settings.ollama_model` (default `llama3.2:3b`) and
embedding model `nomic-embed-text` (`backend/config.py:10-11`), both served by
Ollama over HTTP (`backend/services/llm_service.py:231`,
`backend/services/rag_service.py:44`).

---

## Data flows

### Lab PDF upload — `POST /upload/pdf`
1. The PDF is saved to `settings.upload_dir` under a generated
   `timestamp_uuid` name; the original filename is not persisted
   (`backend/routers/upload.py:46-56`).
2. `PDFParser` extracts values with pdfplumber and regular expressions; lab
   names are normalised by `LabNormalizer` inside the parser
   (`backend/ingestion/pdf_parser.py:214,450,497`). No LLM is involved.
   Rows whose name is a patient/document header field (ID, address, referral,
   a doctor's NEAK line…) are dropped, because multi-page reports repeat the
   header after the results table; only their count is reported as a warning
   (`backend/ingestion/pdf_parser.py:207,382`).
3. Each value is stored as a `LabResult` row and embedded as `lab_result` by
   `store_lab_results` (`backend/services/lab_ingest.py:25,41,44`, called at
   `backend/routers/upload.py:63`). Parse warnings are returned to the caller
   (`backend/routers/upload.py:73`).
4. After a parser fix, `python -m scripts.reimport_labs` (dry run by default,
   `--apply` to write) re-parses the stored PDFs through the same
   `store_lab_results` path: the newest upload of each identical PDF is
   replaced, older copies are removed, and for a missing PDF only header-like
   rows are removed (`backend/scripts/reimport_labs.py`).

### Wearable upload — `POST /upload/samsung`
Exactly one export ZIP is accepted and parsed in memory; nothing is written to
disk, so the client-supplied filename cannot steer a write path, and the export
(whose filename carries the Samsung account name) is not retained. Rows store a
generated `samsung_<timestamp>_<uuid>` identifier, never the original filename
(`backend/routers/upload.py:95,101,104`). Daily summaries are upserted into `samsung_health_metrics`, keyed on
`(metric_type, recorded_at)` (`backend/routers/upload.py:77-157`). A Samsung
upload also stores one `samsung_summary` embedding
(`backend/routers/upload.py:157`). Rows written by the former Zepp Life
import (metric types such as `resting_hr`, `sleep_total_min`, `avg_spo2`,
`avg_stress`) remain in the table; the import itself has been removed.

### Blood pressure — `POST /bp/`
The reading is stored, classified per AHA 2017 and a `bp_classification`
row is written to `risk_scores` (`backend/routers/blood_pressure.py:83-96`).

### Family history — `POST /family-history/`, `DELETE /family-history/{id}`
The entry is stored and embedded as `family_history`; if an ICD-10 code was
entered, that code is looked up on MedlinePlus Connect, and the summary and
link are returned with the entry (`backend/routers/family_history.py:79-105`).
`GET /family-history/` attaches each entry's MedlinePlus info read from the
cache only, with no request (`backend/routers/family_history.py:44-62`); the
Family History page shows it with a link. Deleting an entry also deletes its
embedding, so chat retrieval no longer returns it
(`backend/routers/family_history.py:126-133`).

### Chat — `POST /chat/`
0. An explicit risk question (a `RISK_KEYWORDS` match that is not a "what if"
   question; the no-keyword fallback does not count) is answered without the
   LLM: the reply lists the stored risk inputs with dates, or "no data", and
   `ChatResponse.data_request` carries the same status
   (`backend/routers/chat.py:802`, `backend/services/risk_inputs_text.py`).
   The chat page then shows an inline form, prefilled with the stored values,
   that saves through `PUT /risk/inputs` (and `POST /bp/`) and calculates
   through `POST /risk/calculate` (`frontend/risk_form.py`).
1. Language detection and keyword intent detection
   (`backend/routers/chat.py:798,806`).
2. SQL context builders run only for the detected intents: date-specific,
   wearable metrics, lab trends, blood pressure, family history, risk scores
   (`backend/routers/chat.py:816-855`).
3. Risk scores: baseline scores are computed and persisted by
   `compute_baseline_scores`; hypothetical ("what if") scores are computed in
   memory (`backend/routers/chat.py:589,596-730`).
4. RAG: the message is embedded with nomic's `search_query: ` prefix (stored
   texts use `search_document: `; `backend/services/rag_service.py:29`) and the
   nearest `embeddings` rows by cosine distance are retrieved, with no
   source-type filter (`backend/services/rag_service.py:135,180`). Operating
   point: top `rag_top_k` = 1 row with similarity >= 0.62
   (`backend/config.py:24-25`), chosen with the retrieval eval
   (`python -m eval.retrieval_eval`): recall 85% (HU 70%, EN 100%) at 85%
   precision on 20 HU/EN questions, and none of 5 off-topic questions retrieves
   a row (measured on 42 stored records after the lab re-import). Re-run the eval and `python -m scripts.reembed` after changing the
   model or the texts.
5. MedlinePlus references: for the labs intent, lab-test texts for labs the
   user has results for (first those named in the message, then flagged
   ones); for the family intent, the texts of the family-history ICD-10
   codes. All are read **from the cache only**, with no network call, one per
   MedlinePlus page, trimmed to whole sentences and capped at
   `MAX_REFERENCES` = 3 (`backend/routers/chat.py:835-843`,
   `backend/services/medlineplus_context.py`). They go into a separate
   `<reference>` block labelled as general MedlinePlus text, not about the
   user. The cache is filled by `python -m scripts.warm_medlineplus --apply`
   for the fixed LOINC list in `backend/services/lab_loinc.py`; expired
   entries are still used until the script is rerun.
6. History: the client sends every earlier turn with its `source`. UI error
   turns are dropped together with the question they answered; replies the
   app produced without the LLM are kept with an "[Automatic reply …]" prefix
   (`backend/services/chat_history.py`, applied at
   `backend/routers/chat.py:869`). The rest is fitted into the window:
   `llm_num_ctx` (8192, sent as Ollama's `num_ctx`) minus the 512-token reply
   budget, a safety margin and the estimated system prompt and question;
   the oldest turns are dropped first (`build_messages` in
   `backend/services/llm_service.py`). Tokens are estimated at 2.5
   characters per token (measured 2.68-2.78 on real prompts); a warning is
   logged when Ollama's `prompt_eval_count` shows the estimate was too low.
7. Everything is formatted into the system prompt and sent to Ollama
   `/api/chat` (`backend/routers/chat.py:867`,
   `backend/services/llm_service.py:231`). The response cites only the
   MedlinePlus pages put into the prompt (`backend/routers/chat.py:887-891`).

### Recommendations — `GET /recommendations/`
Baseline risk scores are computed and persisted, then hard-coded
`SCREENING_RULES` are matched against age, sex, family history and flagged labs;
each matched condition is looked up on MedlinePlus for a summary and link
(`backend/routers/recommendations.py:36-55`,
`backend/services/screening_service.py:42,143,178`).

### Risk inputs and scores — `GET/PUT /risk/inputs`, `POST /risk/calculate`
- `GET /risk/inputs` reports every stored input with its date and status
  (`ok`, `stale`, `missing`, or `unconvertible` for a lab unit that cannot be
  converted), and what each score still lacks
  (`backend/services/risk_inputs.py:collect_inputs`). Stale thresholds:
  `risk_measurement_stale_days` (weight, waist, BP) and `risk_lab_stale_days`
  (`backend/config.py`); a stale value stays usable.
- `PUT /risk/inputs` validates the form (plausibility ranges per unit,
  consistent answers; `backend/models/api_models.py:ProfileData`,
  `RiskInputsUpdate`) and saves it in one commit: the single `user_profile`
  row is upserted; a fresh weight or waist is added to
  `samsung_health_metrics` (`weight_kg`, `waist_cm`) and a typed cholesterol
  value to `lab_results` with its unit, all under a generated
  `manual_<timestamp>_<uuid>` source (`backend/services/risk_inputs.py:save_inputs`).
  Typed lab values have no reference range and are not embedded.
- `POST /risk/calculate` computes and persists the baseline scores through
  `compute_baseline_scores` and returns them with the input status
  (`backend/routers/risk.py`).

### Dashboard — `GET /dashboard/summary`
Reads lab results and the five latest `risk_scores` rows
(`backend/routers/dashboard.py:25,45`).

---

## Data stores

- **PostgreSQL tables** (`backend/models/db_models.py`): `user_profile` (:39),
  `lab_results` (:81), `blood_pressure_readings` (:99), `family_history` (:115),
  `samsung_health_metrics` (:131), `embeddings` (:151), `medlineplus_cache`
  (:165), `risk_scores` (:178).
- **Profile**: one row with birth year and month (age is derived, never
  stored), biological sex, height and the yes/no risk answers; weight and
  waist are dated measurements in `samsung_health_metrics`
  (`backend/models/db_models.py:39`).
- **Schema creation**: at startup, `CREATE EXTENSION IF NOT EXISTS vector` and
  `create_all` (`backend/database/connection.py:31-32`). Alembic is configured
  but `backend/database/migrations/versions/` holds no migrations. An existing
  `user_profile` table with the old columns is recreated by
  `python -m scripts.migrate_user_profile --apply`, only while it is empty.
- **Vector store**: `embeddings.embedding` is `Vector(768)`
  (`backend/models/db_models.py:161`). Only three source types are written:
  `lab_result` (`backend/services/lab_ingest.py:41`), `samsung_summary`
  (`backend/routers/upload.py:157`), `family_history`
  (`backend/routers/family_history.py:91`). Lab and family-history texts are
  one bilingual line per record built by `backend/services/embedding_text.py:15,44`
  (the report's own test name next to the normalised key); no chunking. No
  medical literature or guideline text is embedded.
- **Files**: uploaded PDFs are kept on disk in `settings.upload_dir`
  (`backend/config.py:13`), mounted from `./data/uploads` in Compose
  (`docker-compose.yml:68`).

---

## External calls

| Call | From | What is sent | Evidence |
|---|---|---|---|
| Ollama (local container) | backend | Prompts and texts to embed; stays on the host | `backend/services/llm_service.py:231`, `backend/services/rag_service.py:44` |
| MedlinePlus Web Service | backend | A topic search term | `backend/config.py:14`, `backend/services/medlineplus_service.py:135-139` |
| MedlinePlus Connect (web service) | backend | An ICD-10 code; the fixed LOINC list (warm-up script only) | `backend/config.py:17`, `backend/services/medlineplus_service.py:189-196` |

Streamlit usage statistics from the frontend are disabled
(`frontend/.streamlit/config.toml:7`).

MedlinePlus calls are rate-limited and cached for `medlineplus_cache_ttl_days`
(`backend/services/medlineplus_service.py:56-101,294-353`). The chat never
calls MedlinePlus; it reads the cache only.

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
   (`backend/services/risk_score_service.py:97-113,141-154`); the hypothetical
   fallback uses the same converter (`backend/routers/chat.py:552-557`).
   FINDRISC is likewise skipped without age, male/female sex, BMI (weight
   and height) or waist circumference, instead of scoring them as 0 points
   (`backend/services/risk_score_service.py:67-94,195-206`); a "what if"
   question names the missing input (`backend/routers/chat.py:622-632`).
   Exception: cholesterol values typed into a "what if" question carry no unit
   and are read as mg/dL (`backend/routers/chat.py:655-664`); values in the
   mmol/L range are rejected by the plausibility guard
   (`backend/services/risk_engine.py:171-182`), the error is logged and no
   hypothetical score is shown (`backend/routers/chat.py:728-729`).

2. **Hypothetical ("what if") recalculations are never persisted.**
   The hypothetical branch only reads from the database
   (`backend/routers/chat.py:543,562,572,625`) and returns its results in memory
   (`backend/routers/chat.py:596-730`); only baseline scores are persisted, via
   `compute_baseline_scores` (`backend/routers/chat.py:589`,
   `backend/services/risk_score_service.py:311-338`). Locked by
   `test_hypothetical_scores_are_never_persisted`
   (`backend/tests/test_chat_hypothetical.py`).

3. **Retrieved data is wrapped in tagged blocks and the prompt instructs the
   model never to treat it as instructions.**
   Tags: `backend/services/llm_service.py:40-71` (the user's data blocks and
   the MedlinePlus `<reference>` block); rules:
   `backend/services/llm_service.py:74-75`; template tests:
   `backend/tests/test_llm_service.py`,
   `backend/tests/test_medlineplus_references.py`. Whether the model obeys cannot be
   enforced in code. UI error messages never reach the model as its own
   words, and replies the app produced without the LLM are marked as such
   (`backend/services/chat_history.py`; tests:
   `backend/tests/test_chat_history.py`). Client-supplied conversation history
   accepts only `user` and `assistant` turns, so no client can inject a
   system message
   (`backend/models/api_models.py:118-143`; tests:
   `backend/tests/test_chat_hardening.py`).

4. **The backend's only external call is MedlinePlus; it receives condition
   or topic terms only:**
   - the ICD-10 code the user entered for a family-history entry; the
     free-text condition is never sent (`backend/routers/family_history.py:95-97`);
   - screening condition names from the hard-coded `SCREENING_RULES`
     (`backend/services/screening_service.py:42,178`). Which names are sent
     depends on the user's age, sex, family history and flagged labs, so the
     set of queries indirectly reflects that profile;
   - the fixed LOINC list (`backend/services/lab_loinc.py`), sent in full by
     `scripts/warm_medlineplus.py` regardless of the user's results, so it
     reflects nothing about the user. Chat questions trigger no MedlinePlus
     request (`backend/services/medlineplus_context.py`).

5. **The user's own records are never presented as an external source.**
   The prompt labels retrieved context as "semantic search over stored health
   records" from "the user's own records"
   (`backend/services/llm_service.py:63,74`); chat responses cite only the
   external MedlinePlus pages whose text was put into the prompt, never the
   user's records (`backend/routers/chat.py:887-891`). When retrieval fails, the context only
   says "(Context retrieval unavailable.)" and the error goes to the log
   (`backend/routers/chat.py:860-863`).

6. **No usage telemetry leaves the host.**
   Streamlit's `browser.gatherUsageStats` defaults to `true`; it is set to
   `false` in `frontend/.streamlit/config.toml:7`, which the frontend image
   copies into its working directory (`frontend/Dockerfile:3,13,19`).

7. **Services are reachable only from the host.**
   Every published port is bound to `127.0.0.1` (`docker-compose.yml:12,24,65,77`);
   services reach each other over the Compose network by service name. The
   API has no authentication, so this binding is what keeps other machines
   on the network away from the data.

8. **Risk scores that cannot be computed correctly are not shown.**
   The female Framingham points-to-risk table is a placeholder copy of the
   male table (`backend/services/risk_engine.py:107-114`).
   `framingham_supported` allows only the validated male table
   (`backend/services/risk_engine.py:122-136`); otherwise no baseline score is
   computed or saved (`backend/services/risk_score_service.py:155-159`) and a
   "what if" question gets an explicit "Not available" instead of a number
   (`backend/routers/chat.py:671-676`).

### (b) Targets — NOT yet implemented

- **Target:** if requested data does not exist, the assistant says so instead
  of answering. Today only default placeholder strings are passed
  (`backend/services/llm_service.py:207-208`); nothing prevents an answer.
- **Target:** the LLM runs only when needed. Today every chat message calls the
  LLM (`backend/routers/chat.py:867`), except an explicit risk question
  (`backend/routers/chat.py:802`).
- **Target:** MedlinePlus content is used in chat answers. Partly met: lab-test
  and family-history condition texts reach the prompt (Chat step 5);
  screening summaries do not yet.
