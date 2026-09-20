# Test fixtures

These JSON files are **synthetic-but-realistic** response shapes built from the
official API documentation summarized in `docs/PROVIDERS.md`. They exist because no
live API credentials (PQAI token, USPTO ODP key, PatentsView key) were available when
the contract tests were written.

**Action:** once credentials are configured, re-record fixtures from real responses
(respx intercepts live calls if pointed at real hosts; otherwise capture with curl)
and update the verification dates in `docs/PROVIDERS.md`.
