# Provider verification record (spec section 7.2 `VERIFY` items)

> Every fact below was checked against official sources on the date listed.
> Re-verify before relying on a provider after long gaps; this ecosystem churns.

## PQAI — primary semantic search (verified 2026-09-20)

| Item | Finding | Source |
|------|---------|--------|
| Endpoint | `https://api.projectpq.ai` | Official API Usage Guide (`api.projectpq.ai/docs`) |
| Search route | `GET /search/102/` (prior-art documents); `/search/103/` for combinations | Same |
| Key parameters | `q` (text, can be paragraph-long), `n` (count), `offset`, `type` (`patent`/`npl`), `after`/`before` (dates), `cc` (country codes), `snip`, `maps` | Same |
| Response | JSON object with a `results` array of document items | Same |
| Auth | **Token required.** Docs now state API access is part of the PQAI+ subscription; the older page said to email `sam@projectpq.ai` for a token. **Spec deviation:** spec 7.2 assumed free + no API key. | Same + `projectpq.ai/api-old/` |
| Coverage | US patents only (per docs "only US patents as of now") | Same |
| Open items | Exact result-item field names (`id`/`title`/`abstract`/`score`) confirmed from the guide's example flow; re-confirm against a live response once a token is available. Rate limits not published — we run a conservative 1 req/s bucket. | — |

## USPTO Open Data Portal (ODP) — US metadata + file wrapper (verified 2026-09-20)

| Item | Finding | Source |
|------|---------|--------|
| Endpoint | `https://api.uspto.gov` | Official swagger (`data.uspto.gov/swagger/swagger.yaml`) |
| Search | `GET /api/v1/patent/applications/search?q=<lucene>&offset=0&limit=25[&fields=...]` (POST JSON variant exists) | Same |
| Query syntax | Lucene: `AND`/`OR`/`NOT`, wildcards, exact phrases, `field:value` (e.g. `applicationNumberText:14412875`), date ranges | Same |
| Auth | Free API key from data.uspto.gov, sent as `X-API-KEY` header. **Requires a MyUSPTO account linked to a verified ID.me identity.** Unused keys are deleted after 90 days of inactivity. | Getting Started + `patent-dev/uspto-odp` README |
| Claims | **Not available.** The Patent Application API serves bibliographic/file-wrapper data (metadata, continuity, assignments, documents). No parsed claim text. **Spec deviation:** spec 7.2 hoped for claims; the claims chain must rely on the Google Patents page fallback (and later, bulk XML). | Same |
| Rate limits | Published on `data.uspto.gov/apis/api-rate-limits` (numbers not captured yet — re-verify when a key exists). We default to a conservative bucket. | Same |
| Open items | Exact response item field names (`patentFileWrapperDataBag` vs `patentBag`, title field) — adapter maps defensively; confirm on first live call. | — |

## PatentsView — enrichment only (verified 2026-09-20)

| Item | Finding | Source |
|------|---------|--------|
| Endpoint | `https://search.patentsview.org/api/v1/patent/` (POST JSON: `q`, `f`, `o`) | PatentsView docs via migration notices |
| Auth | Free API key required (sent as `X-API-KEY`) | Same |
| Role | Assignee/CPC enrichment **only**; never a claims source | Spec 7.2 |
| Migration watch | PatentsView is being folded into the USPTO Open Data Portal (ODP release 3.4 surfaced PatentsView bulk products). Expect endpoint churn; keep adapter thin. | `patent-dev/uspto-odp` README |

## EPO OPS — feature-flagged, not implemented (2026-09-20)

OAuth client-credentials against `ops.epo.org`, XML responses, quota-limited.
Remains behind `ENABLE_EPO=false` per spec; implementation deferred to keep Phase 1b small.

## Google Patents page — claims fallback (implemented 2026-09-20)

`app/providers/google_patents_page.py` (`GooglePatentsPageProvider`, wired as the
second claims source in `ProviderRegistry`: `USPTO_ODP -> GOOGLE_PATENTS_PAGE`).

- URL is built from the normalized id only: `https://patents.google.com/patent/<ID>/en`.
- SSRF enforcement: `validate_page_url()` (https + allowlist), DNS resolved in a
  worker thread and every IP checked with `is_allowed_ip()` (blocks metadata IP,
  private ranges, IPv4-mapped IPv6), redirects never followed (httpx default),
  ~2 MB response cap, real `User-Agent` from `provider_user_agent` setting.
- Parsing: stdlib `html.parser` keyed on `itemprop="claims"` section, then
  `claim-text` blocks; independent vs dependent via claim-reference regex. Anything
  unrecognized returns `None` (drop-not-guess, spec 11.1).
- Selectors are provisional — re-confirm against live HTML once a real page is
  fetched; fixture `tests/fixtures/google_patent_page.html` is synthetic.
- Open item: true streaming size cap (current cap is checked post-download).

## Fixture note

`tests/fixtures/*.json` are synthetic-but-realistic shapes built from the documented
schemas above (no live credentials were available at write time). When live tokens/keys
are obtained, re-record fixtures from real responses and update the dates in this file.
