# KİK / EKAP API Research (Milestone M-16)

## Overview

Kamu İhale Kurumu (KİK) is the Turkish Public Procurement Authority.
EKAP (Elektronik Kamu Alımları Platformu) is their electronic procurement platform.

This document captures what is known and unknown about the KİK/EKAP API.

---

## Known API Endpoints

| Endpoint (estimated)              | Method | Auth Required | Notes                             |
|-----------------------------------|--------|---------------|-----------------------------------|
| `https://ekap.kik.gov.tr`         | GET    | Yes           | Main portal (HTML, not API)       |
| `https://ekap.kik.gov.tr/api/v2/*`| POST   | Token/Bearer  | Suspected REST API path           |
| `https://www.ihale.gov.tr`        | GET    | No/Public     | Public tender announcements       |

### Notes on Endpoints

- The primary web interface at `ekap.kik.gov.tr` is an HTML application, not a REST API.
- A REST API v2 has been reported in some developer circles, but is **not publicly documented**.
- The public tender portal (`ihale.gov.tr`) lists active tenders but does not expose a search API for historical decisions.

---

## Authentication Mechanism

### What is Known

- The KİK/EKAP system requires user authentication for most operations.
- Prior testing (see `_known_limitations` in registry.py) returned HTTP 401 when attempting unauthenticated API calls.
- Authentication likely involves one of:
  - **e-Devlet (e-Government) integration** — Users log in via Turkey's national e-Devlet gateway using electronic ID (e-imza) or mobile signature.
  - **EKAP user credentials** — Direct username/password for registered EKAP users.
  - **API token** — Possibly issued after e-Devlet or EKAP login, used as a Bearer token in HTTP headers.

### What is Unknown

- Exact token endpoint URL (e.g., `/api/v2/auth/token`).
- Token format (JWT, opaque string, session cookie).
- Token lifetime and refresh mechanism.
- Whether API access is available independently of the web portal.
- Whether a service account or machine-to-machine auth flow exists.

### Recommended Approach

For optional activation, support:
1. **Bearer token** via `KIK_API_TOKEN` or `EKAP_API_TOKEN` environment variables.
2. Token passed as `Authorization: Bearer <token>` header.
3. Graceful degradation to UNAVAILABLE when no token is configured.

---

## Rate Limits

- **Unknown.** No public documentation found.
- Assume conservative rate limits (e.g., 10-30 requests/minute) if the API exists.
- Implement client-side throttling as a precaution.

---

## Known Response Format

Based on the existing placeholder and general Turkish government API patterns:

- Responses are likely JSON.
- Search results would include fields like:
  - `ihaleId` (tender ID)
  - `ihaleAdi` (tender name)
  - `ihaleTarihi` (tender date)
  - `idariAdi` (administrative unit)
  - `turu` (tender type)
- Document retrieval would include procurement decision text or PDF links.

---

## Gaps and Recommendations

| Gap                               | Recommendation                                      |
|-----------------------------------|-----------------------------------------------------|
| No public API documentation       | Document what is discoverable; accept community input|
| Auth flow unknown                 | Gate behind optional token; never hard-code creds   |
| Response schema unknown           | Start with metadata-only; extend when schema known  |
| Rate limits unknown               | Add configurable delays; respect 429 responses      |
| e-Devlet complexity               | Out of scope for initial implementation             |

---

## Implementation Decision

The KİK adapter is implemented with **optional token-based activation**:

- **No token configured** → Source status is `UNAVAILABLE` (current behavior preserved).
- **Token configured** → Source status becomes `EXPERIMENTAL`.
- **Token present + `online=True` smoke test** → Verifies token with a lightweight request.

This approach:
- Preserves backward compatibility (no breaking changes).
- Allows early adopters to test if they have EKAP access.
- Avoids making unauthenticated API calls that would fail with 401.
