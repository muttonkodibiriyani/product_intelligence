"use strict";
// Stub for promptfoo's optional `jks-js` dependency (see the decision log, 2026-10-02). The real
// package pulls node-forge <= 1.4.0 (GHSA-86w9-cpqp-85rv, no patched version). Our suites never
// load a Java keystore, so any use fails loudly instead of loading vulnerable crypto.
function unsupported() {
  throw new Error("JKS keystores not supported");
}

module.exports = { toPem: unsupported, parseJks: unsupported };
