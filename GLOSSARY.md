# GLOSSARY

Domain vocabulary for hackathon-radar. Use these terms exactly; don't drift to synonyms.

- **Event** — one hackathon record in normalized form (see `radar/models.py::Event`).
- **Source** — a platform we scrape (devpost, devfolio, …), registered in `radar/sources.yaml`.
- **Adapter** — the code unit for one source (`radar/adapters/<id>.py`); kind = `api | browser | hybrid`.
- **Kind** — how an adapter fetches: `api` (JSON endpoint, httpx), `browser` (page render via CloakBrowser), `hybrid` (both).
- **Run** — one execution of `radar run`: fetch → normalize → render → commit.
- **Live table** — `data/hackathons.md`: events with status `open` or `upcoming`.
- **Archive** — `data/archive.md`: events whose registration/event ended (status `closed`), kept as history.
- **days_left** — whole days from the run date (IST) to `reg_deadline`; null when unknown.
- **first_seen / last_seen** — timestamps of first observation and most recent successful observation of an event.
- **also_on** — other sources listing the same event (dedupe merge), e.g. `["devfolio", "devpost"]`.
- **extracted_by** — provenance of a row: `api`, `css`, or `llm` (rare fallback).
- **Stale row** — last-known row retained after its source failed in the current run (last_seen unchanged, source listed in `failed[]`).
- **M0–M4** — milestones from the implementation plan (spike → skeleton → adapters → first run → end-cap).
