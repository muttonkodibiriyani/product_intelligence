# Architecture (overview)

The platform is a factory with five stations. Full detail is in [`docs/blueprint.md`](docs/blueprint.md).

| Station | What happens | Main components |
|---|---|---|
| 1. Collect | Robots capture every product, variant, field and image on a schedule, escalating their method automatically when a site resists | Source register, Dagster orchestrator, connectors + escalation ladder (`pi_fetch`), image pipeline (`pi_images`) |
| 2. Check | Values are normalised and tested; suspicious data goes to quarantine, never to reports | `pi_normalize`, `pi_quality` (Pandera), dbt tests |
| 3. Match | Identical / comparable products are linked; uncertain pairs go to human review | `pi_match` (rules → Splink → text+image embeddings → Gemini → review) |
| 4. Calculate | One tested set of formulas produces every number | dbt marts + Cube semantic layer |
| 5. Show | Web app, compare board, alerts, AI assistant and exports all read from station 4 | Next.js (Firebase App Hosting), Genkit + Gemini |

## Platform

All on one Firebase / Google Cloud project:

- **Firebase Auth + Identity Platform**: login, MFA, SSO-ready
- **Data Connect (Cloud SQL PostgreSQL 16 + pgvector)**: catalogue, append-only observations, matches, audit
- **Cloud Storage**: raw evidence (90 days), product images
- **Firestore**: app state (boards, alert settings)
- **App Hosting / Cloud Run**: web app and jobs
- **Secret Manager**: proxy and API credentials
- BigQuery: only when volume demands it

## Non-negotiables

- Observations are append-only; corrections are new versions.
- Missing is not zero: explicit availability states, null + reason for fields.
- Money is `Decimal` with a currency, never float.
- One metric service feeds UI, API, exports and AI.
- No paid cloud resource or proxy without the owner's approval.

## Environments

`local` (Docker Compose + Firebase emulators, $0) → `dev` (Firebase project) → `prod`.
