# Ulta UAE connector

Offline-only discovery and parsing groundwork for `ulta.ae`. This package makes no network
requests and must not import HTTP or browser clients. Raw documents are supplied by the shared
`pi_fetch` runner after policy, pacing, block detection, and evidence capture.

All committed fixtures currently have `SYNTHETIC` in their filename. They describe the expected
field contract but are not evidence of the live site's layout. Replace or supplement them with
cookie-stripped recorded fixtures only after the Gulf probe and access-method approval.

`_pi_fetch_stub.py` mirrors interface sketch v0.1 and is temporary until `pi_fetch` and the PR #6
`pi_core` records land. The eventual canonical-record mapping is marked next to the source models.
