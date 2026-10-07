# pi-api admission records

One `<dataset>.json` per dataset served over `V3_MAX_BYTES` (`pi_dataset.gate`), written by
`infra/scripts/pi_api_admission.py measure` and read by its `check` before a deploy. A record
admits one exact body: the sha256 of the decompressed `latest.json` pi_api parses. Procedure and
pass rule (highest refresh peak ≤ 75% of memory): `docs/runbooks/pi-api-deploy.md` §6.
