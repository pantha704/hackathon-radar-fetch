# ADR 0001: Walled sources — unstop.com and hackerearth.com excluded from v1

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

hackathon-radar aims to list every findable hackathon, and source coverage is a core value — so excluding a source is a decision that needs an explicit record, not a silent omission.

During the M0 probe (2026-10-09), each candidate source was tested through the project's fetch stack. Two platforms refused every route tried with **HTTP 403**:

- `unstop.com`
- `hackerearth.com`

Routes tried:

1. Plain `curl` from the VPS — 403.
2. A rendered visit through CloakBrowser (the project's stealth browser, full JS rendering, normal browser fingerprint) — 403.

Because the stealth browser was refused too, the block is classified as an **IP-level wall against the datacenter IP**, not a JS or markup problem. Every other probed source (devpost, devfolio, dorahacks, mlh, superteam, lablab, ethglobal, taikai, hackathon.com, wemakedevs, hackclub) was reachable and now has an adapter — 11 sources live.

Policy constraints in force: no credential capture; browser sessions only via the stealth browser; no fake or stale rows — a source that cannot be fetched honestly is excluded, and its absence is documented, never papered over.

## Decision

Exclude `unstop.com` and `hackerearth.com` from the v1 source set:

- Neither is registered in `radar/sources.yaml`, and neither has an adapter in `radar/adapters/`.
- The radar reports source failures explicitly — a failing source appears in the run's `failed[]` list, never hidden. These two are outside that mechanism: with no `sources.yaml` entry, they are never attempted, so they can never appear in `failed[]`. Their absence is made visible by this ADR and by the README (Task 12).
- If either becomes fetchable later, adding it follows the existing browser-adapter pattern (`kind: browser`: one `sources.yaml` entry plus one adapter module) and can be done in a single cycle.

## Consequences

- The v1 catalog contains no unstop or hackerearth rows; this is a known coverage gap.
- The README (Task 12) will acknowledge the coverage gap and link this ADR.
- Re-probing is cheap: `.venv/bin/python scripts/probe_fetch.py <url>` fetches any URL through the project's stealth browser, so the wall status of either platform can be re-tested whenever needed.

## Revisit triggers

- **Residential-IP route available** — the operator's residential-IP route via out-of-repo phone-tunnel tooling (no tunnel script found on the box). Adopting it as a fetch route for the radar is a candidate future extension, not implemented now.
- **Wall status changes** — any non-403 response on re-probe (`.venv/bin/python scripts/probe_fetch.py <url>`) reopens this decision.
- **Session-based wall** — if the wall turns out to require a login session rather than a different IP, the route is a logged-in stealth-browser profile, subject to the no-credential-capture policy.
