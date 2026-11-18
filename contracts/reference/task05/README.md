# TASK-05 Final Approved Reconstructed Reference Contract Bundle

## Authority and scope
- TASK-05 owner-approved design, all T5-CLOSE-01..08 and T5-DEC-01..20.
- The original REVIEW DOCX referred to an unavailable schema/examples/verifier bundle. This new bundle is **reconstructed** and now the approved contract reference; there is no byte-parity claim.
- `schemas/wire-vocabulary-v1.json` freezes TASK-05-specific wire spellings; upstream routing, ARP and scheduling behavior remains unchanged.

## Reproduce
```bash
python -m pip install jsonschema
python tools/verify_contract.py
```
Expected from this revision: **58/58 PASS** (10 positive examples + 48 negative mutations). Test runner rewrites `reports/contract_verification_results.json` deterministically.
Run `sha256sum -c manifest.sha256` to check bundle bytes before or after verification (if no edits).

## Audit
See `reports/TASK-05_Final_Acceptance_Coverage_Audit.md`. Only 3 of 40 full source acceptance scenarios have complete contract-level synthetic proof; 16 partial, 21 not executed. Real simulator/DB/API/Unity/AI integration not run.

## Components
- `schemas/task05-contract-v1.schema.json` -- Draft 2020-12 structural schema
- `schemas/wire-vocabulary-v1.json` -- normative TASK-05 wire string inventory and typing
- `examples/*.json` -- ten synthetic complete documents, not traces
- `tools/verify_contract.py` -- schema and fixture semantic validation
- `reports/` -- check-by-check results and 40-case audit
- `manifest.sha256` -- per-file integrity list
