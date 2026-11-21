# Proof manifest

Build `11d25d824c8f`. Every headline number in the Command Center, the proof run that
produced it, and that file's SHA-256. Recompute a hash to confirm nothing was edited by hand.

| Claim | Value | Proof file | SHA-256 |
|---|---|---|---|
| Bank variance on assessed merchant-days | `0.00` | `docs/artifacts/html/02_halala_recon_board.html` | `66b5f109658fd06f…` |
| GL variance on assessed merchant-days | `0.00` | `docs/artifacts/html/02_halala_recon_board.html` | `66b5f109658fd06f…` |
| Merchant-days not assessed (bank file pending) | `112` | `docs/artifacts/html/02_halala_recon_board.html` | `66b5f109658fd06f…` |
| ZATCA chain breaks | `0` | `docs/artifacts/html/01_zatca_chain_tape.html` | `e6fa256f930d3335…` |
| Worker restarts survived mid-submit | `1` | `docs/artifacts/html/01_zatca_chain_tape.html` | `e6fa256f930d3335…` |
| Gold columns traced to source | `94` | `dbt/target/manifest.json` | `8a2ad7744254fef3…` |
| Gold columns in total | `94` | `dbt/target/manifest.json` | `8a2ad7744254fef3…` |
| dbt models passing on Fabric | `99` | `docs/artifacts/10_fabric_run_evidence.json` | `e80a62da65876659…` |
| Spark skew benchmark rows | `20000000` | `docs/artifacts/05_skew_benchmark_20m.json` | `85b1bab4a9f0c208…` |
| PDPL keys shredded on one erasure | `5` | `docs/artifacts/html/03_pdpl_shred_restore.html` | `16a946738bc39537…` |
| PDPL Restore Guard re-shredded a restore | `5` | `docs/artifacts/html/03_pdpl_shred_restore.html` | `16a946738bc39537…` |
| Signed tax rows kept under legal hold | `25001` | `docs/artifacts/html/03_pdpl_shred_restore.html` | `16a946738bc39537…` |
| Arabic MDM golden customers | `2552` | `docs/artifacts/html/04_arabic_mdm_board.html` | `77b2f407c2d889b6…` |

Regenerate with `.\.venv\Scripts\python.exe scripts\build_proof_manifest.py`.
