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