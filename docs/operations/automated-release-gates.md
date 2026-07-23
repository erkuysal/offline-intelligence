# Automated Release Gates

The Phase 9 release gate runner converts the independent source, test, bundle, provenance, signature,
and policy checks into one fail-closed decision. It validates a candidate; it does not sign, tag,
publish, install, or promote one.

## Trust boundary

Run the gate from a detached clean checkout at the exact candidate revision. The source gate runs
before any child command and rejects tracked or untracked changes, forbidden caches, dependency
directories, local environment files, symlinks, and missing required release files. Later commands
may create ignored build state only after that clean snapshot passes.

Copy
[`release-gates-v1.example.json`](../../config/supply-chain/release-gates-v1.example.json)
outside the checkout or into ignored release state. Set:

- `release_id` to the candidate bundle's exact release ID;
- `expected_revision` to the full lowercase 40-character candidate Git SHA;
- bundle, provenance, signature, and public-key paths to the candidate inputs.

Do not put passwords, tokens, private keys, authorization headers, document text, or private prompts
in the specification. Verification needs only the detached signature and public key. Supply any
runtime-only secret through the controlled process environment.

## Mandatory gates

The schema requires exactly these gates and the runner executes them in this order:

1. `source`
2. `backend_tests`
3. `frontend_tests`
4. `native_tests`
5. `bundle`
6. `sbom`
7. `signature`
8. `container_policy`

The source gate is built in. The other seven are explicit command lists in the version-controlled
specification. A failed or timed-out command blocks every later gate. Cleanup commands still run
after failure. Missing, stale, symlinked, or malformed declared evidence fails its gate. A missing
mandatory gate makes the specification invalid.

The bundle manifest and provenance report must match both `release_id` and `expected_revision`.
The verified signature envelope must name that release ID. A valid older candidate therefore cannot
pass beside tests from newer source.

## Run

Use the project-specific Python environment:

```bash
conda run -n offline-ai python manage.py release-gate-verify \
  --spec /controlled/release-gates.json \
  --source /clean/checkout \
  --report-dir /controlled/reports \
  --log /controlled/reports/release-gates.jsonl \
  --output /controlled/reports/release-decision.json
```

Exit status `0` means every gate passed. Status `1` is a complete negative release decision.
Status `2` means the specification or runner could not be evaluated.

The JSON decision always lists all eight gates. It records statuses, exit codes, durations,
evidence SHA-256 identities, and failures. The JSONL log records command shapes and output byte
counts/digests, but never stores child stdout or stderr. Inline scripts, credential-like arguments,
and credential-bearing URLs are redacted from command metadata. This deliberately trades verbose
failure text for a log that is safe to retain; investigate a failed command in the controlled build
environment using its gate and command index.

All child commands force fake chat and embedding backends. Real model servers are reserved for final
promotion acceptance and require advance operator notice.
