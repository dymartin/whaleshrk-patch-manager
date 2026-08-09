# Patchstorage API

Base `https://patchstorage.com/api/beta/`. No auth, no rate-limit headers.

Working filters on `/patches`: `platforms`, `tags`, `categories`, `author`
(singular), `search`, `per_page` (max 100), `page`. Pagination via `X-WP-Total`
and `X-WP-TotalPages`.

**Unknown query parameters are silently ignored, not rejected.** `authors=<id>`
returns all 17,000+ patches; `author=<id>` filters correctly. Any sync must
assert result counts rather than trusting a filter.

Relevant ids: platform `orac` = 3371, platform `organelle` = 154, tag `orac` =
1483.

The list endpoint omits `files` entirely — only `/patches/<id>` carries download
URLs. Two list calls give `updated_at` for every candidate; detail-fetch only
what changed.

`revision` is free text and unusable as a version. Real values on the site
include `0.00200.0220.220` and `87798176543`. Use `updated_at` plus the detail
endpoint's file `id`, verified with a content hash.
