# gulf_probe

One-off reachability probe for the UAE pilot sources (task 01a0f3d2-fb2d). Results are in
[`docs/recon/gulf_probe_results.md`](../../docs/recon/gulf_probe_results.md).

It uses ordinary access only: plain `httpx` with normal headers, and stock Playwright
Chromium/Firefox/WebKit. There is no impersonation, stealth, challenge solving or cookie reuse. The
robots.txt of every non-Sephora host is obeyed through a per-host gate.

- `gulf_probe/analysis.py`: block/vendor detection, redaction, product-field extraction and robots
  rules. Pure, typed and tested.
- `gulf_probe/plan.py`: targets, allowed client labels and the `PROBE_SPEC` parser. Pure and tested.
- `gulf_probe/run.py`: I/O runner (GCS or `file:` output). It is excluded from mypy/coverage.

Environment: `PROBE_BUCKET` (bucket name or `file:/dir`), `PROBE_EGRESS` (label), `PROBE_STAGE`
(`1` = built-in plan, else `PROBE_SPEC` JSON), `PROBE_PREFIX`, `PROBE_PACE` (seconds per request,
default 1).

```sh
docker build -t gulf-probe tools/gulf_probe
docker run --rm -v "$PWD/out:/out" -e PROBE_BUCKET=file:/out -e PROBE_EGRESS=local \
  -e PROBE_STAGE=x -e PROBE_SPEC="$(cat spec.json)" gulf-probe
```
