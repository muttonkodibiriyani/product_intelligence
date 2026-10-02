# ADR-0002: Firebase platform with PostgreSQL as the fact store

- Status: accepted
- Date: 2026-09-30

## Context
The owner wants everything on Firebase. The data needs append-only history, joins, group-bys,
point-in-time queries and vector search. Firestore bills per document read and cannot join or
aggregate at analytical scale.

## Decision
- Firebase Auth (+ Identity Platform), App Hosting, Firestore (app state only), Cloud Storage,
  Secret Manager, Genkit + Gemini.
- **Firebase Data Connect / Cloud SQL PostgreSQL 16 + pgvector** is the single fact store
  (catalogue, observations, matches, audit), with monthly partitions.
- BigQuery is added only if volume requires it.
- Development runs locally (Docker Compose + Firebase emulators) at $0.

## Consequences
One project, one bill. PostgreSQL is the only fixed monthly cost; it is created only with owner
approval and kept at the smallest tier during the pilot.

## Amended 2026-10-01: Genkit → `@google/genai` (Vertex/ADC)
The AI assistant calls Gemini through the official `@google/genai` SDK in Vertex mode with
Application Default Credentials only, instead of Genkit. Reason: Genkit's Firebase plugin
brought 49 npm advisories (7 high) through its telemetry dependencies, and the assistant runs its
own metered tool loop anyway. Gemini, Vertex AI and server-side read-only tools are unchanged.
See the decision log (2026-10-01) and `docs/design/ai-assistant.md` §2.
