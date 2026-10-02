# Security

- **Secrets never enter this repository.** Cloud credentials, proxy passwords and API keys
  live in Google Secret Manager (cloud) or git-ignored local files (development).
  CI runs a gitleaks scan on every PR.
- The web app is private: Firebase Auth with MFA; role and attribute permissions are enforced
  in the API and PostgreSQL row-level security, and the AI assistant uses the same path.
- Crawlers never log in with personal accounts, never bypass passwords or paywalls, and never
  place orders. Downloaded content is treated as untrusted data and never executed.
- Scraped text is never used as instructions for the AI assistant (prompt-injection defence).
- Reviews are stored without reviewer names or other personal data.

Report a suspected leak or vulnerability to the repository owner immediately. If a
credential is exposed, rotate it first, then clean up history.
