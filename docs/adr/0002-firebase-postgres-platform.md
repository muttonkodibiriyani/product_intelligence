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
