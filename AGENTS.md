# AGENTS.md — health_assistant

## Git fegyelem (KÖTELEZŐ, minden feladatnál)
- SOHA ne commitolj közvetlenül a `selective_sql_injection` vagy `main`/`master` branch-re.
- Feladat elején mindig: `git status` + `git branch --show-current` — ha a working tree nem tiszta, állj meg és kérdezz.
- Minden önálló javításhoz külön branch a jelenlegi branch-ből ágaztatva:
  `git checkout -b fix/<rövid-leíró-név> selective_sql_injection`
- Ne push-olj (a repo csak lokális), ne merge-elj automatikusan a bázis branch-be, ne rebase-elj meglévő branch-et.
- Kis, atomi commitok, Conventional Commits formátumban, ANGOLUL:
  `fix(rag): filter similarity_search by source_type`
- Minden commit előtt: a kód fusson (`pytest tests/ -v` zöld), és a diff kizárólag a feladat hatókörébe tartozó fájlokat érintse.
- A feladat végén: `git log --oneline <base>..HEAD` és `git diff --stat <base>..HEAD` kiírása — ne csinálj mást a branch-csel (nincs merge, nincs push).

## Clean code szabályok
- Kövesd a meglévő stílust: Google-style docstring-ek (lásd `risk_engine.py`, `rag_service.py`), type hint-ek mindenhol, `from __future__ import annotations`.
- Egy függvény egy felelősség (SRP) — ha egy fix miatt egy függvény 40+ sorosra nőne, bontsd szét.
- Tilos a néma `except Exception: pass` — mindig `logger.warning`/`logger.error` a meglévő minta szerint.
- Ne legyen mágikus szám/string dokumentáció nélkül; konfigurálható értékeket a `config.py`/`Settings`-be vagy modul szintű konstansba tegyél, kommenttel indokolva.
- Ne törölj és ne módosíts olyan kódot, ami nem kapcsolódik a kapott feladathoz (scope discipline). Ha refaktorálási lehetőséget látsz máshol, csak jelezd a végső összefoglalóban, ne írd át.
- Minden módosított/új logikához tartozzon vagy frissüljön unit teszt a `backend/tests/`-ben, a meglévő pytest+pytest-asyncio mintát követve.

## Munkafolyamat
1. Ismertesd röviden a tervet, mielőtt kódot írsz.
2. Csak a megjelölt fájlokat módosítsd, kivéve ha a teszt-lefedettség indokolja egy teszt-fájl hozzáadását.
3. A végén adj összefoglalót: mely fájlok, miért, milyen kockázattal, mi maradt nyitott kérdés.

## Output protocol (lean)

Every task response must include these 5 items, but keep them compact:

1. **Full diff** — unchanged requirement, this is the primary review artifact.
2. **Checklist** — one line per required item: done/not done + file:line.
3. **Test evidence** — run the full suite, but only report:
   - the command used,
   - the final summary line (e.g. `54 passed, 0 failed, 4 warnings`),
   - FULL verbose output for any test that is NEW in this branch,
   - FULL verbose output for any FAILURE.
   Do NOT paste the full list of pre-existing PASSED tests — the summary
   line is sufficient proof they still pass.
4. **Scope check** — one line: which files changed, confirmation nothing
   else touched.
5. **git log --oneline <base>..<branch>** — one line per commit.

## Tiering
- **Mechanical changes** (deletion of confirmed-dead code, import cleanup,
  dependency bumps, config-only additions with no behavior change): items
  1–5 above, minimal prose, no extra discussion needed.
- **Logic changes** (business logic, prompts, SQL, data models, anything
  affecting runtime behavior): same 5 items, plus a short paragraph noting
  any edge cases considered or explicitly out of scope.

This protocol is loaded automatically from AGENTS.md — individual prompts
do not need to restate it in full. A one-line tag "[lean output protocol]"
at the top of a prompt is enough as a reminder for time-pressured runs.

## Testing Protocols
Tests must be run from the `backend/` directory, with these env vars set
first (the repo's `.env` file does not satisfy Settings' required fields
when tests are run outside Docker):
  DATABASE_URL=postgresql+asyncpg://healthuser:pw@localhost:5432/healthassistant
  SYNC_DATABASE_URL=postgresql+psycopg2://healthuser:pw@localhost:5432/healthassistant
Command: cd backend && pytest tests/ -v