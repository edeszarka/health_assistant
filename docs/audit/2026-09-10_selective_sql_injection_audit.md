# Audit — selective_sql_injection (2026-09-10)

Branch: `selective_sql_injection`
Scope: kizárólag audit, kódmódosítás nélkül. A verdiktek a tényleges kód
(fájl + sor) alapján készültek, nem a README vagy kommentek alapján.

---

## 1. `rag_service.similarity_search()` — `source_type` szűrés

**Állítás:** A `similarity_search()` szűr `source_type` szerint (csak pl.
`guideline` típusú embeddinget ad vissza), elkerülve, hogy a saját lab/family
adat "MedlinePlus"-ként jelenjen meg.

**Bizonyíték:**

`backend/services/rag_service.py:108-116`:

```python
stmt = (
        select(Embedding.content)
        .where(
            # only return chunks closer than threshold
            (1 - Embedding.embedding.op("<=>")(vector)) >= threshold
        )
        .order_by(Embedding.embedding.op("<=>")(vector))
        .limit(limit)
    )
```

A `WHERE` kizárólag a threshold-ra szűr, `source_type` filter **nincs**.

`build_context()` hívása (`backend/services/rag_service.py:148`):

```python
similar = await self.similarity_search(query, limit=5, db=db)
```

Semmilyen `source_type` paramétert nem ad át.

Ténylegesen tárolt `source_type` értékek (a grep találatai alapján):

- `"lab_result"` — `backend/routers/upload.py:94`
- `"samsung_summary"` — `backend/routers/upload.py:190`
- `"family_history"` — `backend/routers/family_history.py:58`

`"guideline"` típusú embeddinget **sehol nem tárol** a kód (csak a
`backend/models/db_models.py:116` komment említi mint lehetséges értéket).

Konzisztencia a prompttal: `backend/services/llm_service.py:47` és `:96`:

```text
Additional medical context (from NIH MedlinePlus):
{rag_context}
```

A prompt a RAG kontextust "NIH MedlinePlus"-ként címkézi, miközben az a saját
`lab_result` / `samsung_summary` / `family_history` embeddingeket is
visszaadhatja. A kettő **nem konzisztens**, és pontosan a feladatban leírt
hiba (saját adat → "MedlinePlus" forrásként való visszaadás) áll fenn.

**Verdikt: NEM MEGOLDVA**

---

## 2. `lab_normalizer.py` — LLM-fallback ismeretlen lab nevekre

**Állítás:** A `lab_normalizer.py` LLM-hívást (Ollama/httpx) használ fallbackként
az ismeretlen lab nevekre, ahogy a README "Stage 2" állítja.

**Bizonyíték:**

`backend/ingestion/lab_normalizer.py:1-6` — a fájl teljes importja:

```python
"""Lab result name normalisation: Hungarian/Latin → English standard keys."""

from __future__ import annotations
```

Nincs `httpx`, nincs Ollama, nincs semmilyen API-hívás.

`backend/ingestion/lab_normalizer.py:113-145`:

```python
def normalize(self, raw_name: str) -> str:
    key = raw_name.lower().strip()

    # 1. Exact match
    if key in self.KNOWN_MAPPINGS:
        return self.KNOWN_MAPPINGS[key]

    # 2. Partial match – find the longest matching prefix/substring
    best_match: str | None = None
    best_len = 0
    for known, standard in self.KNOWN_MAPPINGS.items():
        if known in key and len(known) > best_len:
            best_match = standard
            best_len = len(known)

    if best_match:
        return best_match

    # 3. Fallback
    return key
```

A fallback tisztán a lowercased raw name visszaadása, nincs LLM-hívás.

A README állítása (`README.md:180-188`): "Stage 2: unmapped names are sent to
the local LLM with a structured prompt requesting the WHO equivalent" — ez a
kódban **nem létezik**.

**Verdikt: NEM MEGOLDVA**

---

## 3. `rag_service` — 0.75-ös `threshold` konfigurálhatósága

**Állítás:** A 0.75-ös `threshold` kalibrálva/konfigurálhatóvá van téve
(`.env`/`Settings`-ből jön), nem hardcode-olt.

**Bizonyíték:**

`backend/services/rag_service.py:84-96`:

```python
async def similarity_search(
    self,
    query: str,
    limit: int = 5,
    threshold: float = 0.75,
    db: AsyncSession = None,
) -> list[str]:
    ...
        threshold: The minimum similarity score (1 - cosine distance). Defaults to 0.75.
```

A `threshold` default értéke hardcode-olt a szignatúrában.

`backend/config.py:4-16` — a `Settings` osztály:

```python
class Settings(BaseSettings):
    database_url: str
    sync_database_url: str
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    embed_model: str = "nomic-embed-text"
    embed_dimensions: int = 768
    upload_dir: str = "./uploads"
    medlineplus_base_url: str = "https://wsearch.nlm.nih.gov/ws/query"
    medlineplus_connect_url: str = "https://connect.medlineplus.gov/application"
    medlineplus_cache_ttl_days: int = 7
```

Nincs `threshold` / `rag_threshold` mező. A grep szerint a `threshold` kifejezés
csak a `rag_service.py` 88/96/112. soraiban fordul elő.

**Verdikt: NEM MEGOLDVA**

---

## 4. `chat._detect_intent()` — "labs" kulcsszólista vs. `RELEVANT_LAB_TESTS`

**Állítás:** A `_detect_intent()` "labs" kulcsszólistája tartalmazza a
`RELEVANT_LAB_TESTS` halmazban szereplő rövidítéseket (pl. "ldl", "hdl", "tsh",
"ast", "alt", "egfr").

**Bizonyíték:**

`backend/routers/chat.py:90-93` — a "labs" kulcsszólista:

```python
"labs": [
    "lab", "blood test", "result", "cholesterol", "glucose", "creatinine",
    "wbc", "vérkép", "laborlelet", "eredmény", "vércukor", "koleszterin"
],
```

`backend/routers/chat.py:34-45` — `RELEVANT_LAB_TESTS` (részlet, a kérdéses
rövidítésekkel):

```python
RELEVANT_LAB_TESTS: set[str] = {
    "wbc", "rbc", "hemoglobin", "hematocrit", "platelets",
    ...
    "glucose", "hba1c", "bun", "creatinine", "uric_acid", "egfr",
    ...
    "ast", "alt", "ggt", "gamma_gt", "alp", "total_bilirubin", "direct_bilirubin",
    "total_cholesterol", "hdl_cholesterol", "ldl_cholesterol", "triglycerides",
    ...
    "tsh", "free_t4", "free_t3", "crp", "urinalysis", "urine_sediment",
}
```

A "labs" listában a `ldl`, `hdl`, `tsh`, `ast`, `alt`, `egfr` rövidítések
**egyike sem szerepel**. A listában lévő `"cholesterol"`, `"glucose"`,
`"creatinine"`, `"wbc"` teljes szavak, nem a kérdéses rövidítések. Következmény:
pl. a "Mi a TSH-m?" vagy "Mi az LDL-em?" üzenet nem triggereli a `"labs"` intentet
(mert "lab" substring sincs benne), így a `_build_lab_trends_summary()` le sem fut.

**Verdikt: NEM MEGOLDVA**

---

## Összefoglaló

| # | Állítás | Verdikt |
|---|---------|---------|
| 1 | `similarity_search()` szűr `source_type` szerint | NEM MEGOLDVA |
| 2 | `lab_normalizer.py` LLM-fallback | NEM MEGOLDVA |
| 3 | 0.75-ös threshold konfigurálható | NEM MEGOLDVA |
| 4 | "labs" kulcsszólista tartalmazza a rövidítéseket | NEM MEGOLDVA |
