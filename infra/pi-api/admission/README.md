# pi-api admission records

One `<dataset>.json` per dataset that is the largest file of a served set over the memory fit
(`pi_dataset.gate`), written by `infra/scripts/pi_api_admission.py measure` and read by its
`check` before a deploy. A record admits one exact body: the sha256 of the decompressed
`latest.json` pi_api parses, beside other files totalling at most the record's `served` bytes
(a path shared by several sources counts once); `check` prints it as `PI_API_ADMITTED`
(`sha256:others_bytes`), which pi_api enforces at every load. Procedure and
pass rule (highest refresh peak ≤ 75% of memory): `docs/runbooks/pi-api-deploy.md` §6.
