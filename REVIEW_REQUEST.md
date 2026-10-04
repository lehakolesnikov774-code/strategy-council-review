# CURRENT REVIEW REQUEST

## Command from Lesha
When Lesha says **"синхронизируйся"**, use this file as the current task.

## Source of truth
Repository: https://github.com/lehakolesnikov774-code/strategy-council-review
Branch: `main`

Always review the exact current HEAD of `main`. Record that commit SHA in the verdict.

## Required procedure
1. Read `README.md`.
2. Read and verify `MANIFEST.sha256`.
3. Download the exact four artifacts listed in the manifest.
4. Recompute SHA-256 locally and compare every file with the manifest.
5. Run `python -m py_compile forecaster_v11_marfa.py`.
6. Run the complete canonical test suite from `test_forecaster_v11_marfa.py`.
7. Run/review `run_forecaster_e2e_v1.py` to the extent possible with the datasets available in your session.
8. Independently review for reproducible BLOCKER/MAJOR defects. Do not reopen frozen architecture for preference/style differences.
9. Do not invent or placeholder SHA values, stdout, test counts, timestamps, or E2E results.
10. Return **one valid JSON object only**, following `ALICE_VERDICT_TEMPLATE.json`. No prose before or after the JSON.

## Current technical status
- Canonical architecture: v11, frozen unless a reproducible BLOCKER/MAJOR emerges.
- Expected canonical pytest result: 40/40, but report only what you actually execute.
- CAL_V1 status remains `NOT_FOR_PRODUCTION`.
- Calibration protocol for next stage:
  - per-horizon `k_h`;
  - learn on folds 1-3 only;
  - fold 4 untouched during tuning;
  - held-out target coverage 78-82%;
  - held-out interval score <= 34.4936;
  - per-instrument calibration, if introduced, is also trained only on folds 1-3.

## Output
Use exactly the structure in `ALICE_VERDICT_TEMPLATE.json`.
