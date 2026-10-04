# Strategy Council Review Mirror

Public read-only review mirror for independent verification by Alice/Yandex.

## Canonical review package
- `forecaster_v11_marfa.py`
- `test_forecaster_v11_marfa.py`
- `moex_stocks_calibration_candidate_v1.csv`
- `run_forecaster_e2e_v1.py`
- `MANIFEST.sha256` — generated after public raw-file verification.

## Rules for Alice
1. Synchronize from this repository at the start of every review session.
2. Use the exact files in the current `main` commit. Do not reconstruct or shorten them.
3. Verify SHA-256 against `MANIFEST.sha256`.
4. Run `python -m py_compile forecaster_v11_marfa.py`.
5. Run the complete canonical test suite and report factual stdout.
6. Review independently before reading any prior reviewer conclusion.
7. Return concrete, reproducible defects only: file, line/contract, evidence, severity.
8. Architecture is frozen unless a reproducible BLOCKER/MAJOR defect is found.
9. `MOEX_STOCKS_CAL_V1` remains NOT_FOR_PRODUCTION until calibration and shadow criteria are satisfied.

## Current calibration protocol
- Per-horizon interval calibration factor `k_h`.
- Learn on folds 1-3 only.
- Fold 4 is untouched holdout; no tuning on fold 4.
- Success target: held-out coverage 78-82%.
- Held-out interval score must be <= 34.4936.
- Any per-instrument calibration, if introduced, is also learned only on folds 1-3.

## Security boundary
This repository intentionally contains no production credentials, broker tokens, Railway secrets, MAX tokens, database URLs, or private trading infrastructure configuration.
