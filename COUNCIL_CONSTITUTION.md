# STRATEGY COUNCIL CONSTITUTION

## Purpose
This repository is the shared review channel between Marfa and Alice for the Strategy Council.

## Mandatory review cycle
Whenever Marfa changes any canonical review artifact or calibration artifact in this repository, the next mandatory action is:

1. Open the existing Alice/Yandex chat in the Work browser.
2. Send exactly:
   **Алиса, синхронизируйся и дай VERDICT.json**
3. Wait for Alice's response.
4. Validate that the response is valid JSON and follows `ALICE_VERDICT_TEMPLATE.json`.
5. Verify that `source.commit_sha` matches the exact reviewed `main` commit.
6. Verify that reported SHA-256 values match `MANIFEST.sha256`.
7. Reject placeholder or fabricated values.
8. Commit the accepted verdict into `verdicts/`.
9. Only then continue the Strategy Council cycle.

## Human role
Lesha is not a message courier. Human intervention is required only when:
- browser login / 2FA is requested;
- Alice/Yandex blocks browser automation;
- a material reviewer disagreement cannot be resolved after the defined review rounds;
- production/shadow approval requires Lesha's decision.

## Safety boundaries
- Never expose production secrets, broker tokens, Railway variables, MAX tokens, database URLs, or private infrastructure credentials to the public review repository or Alice chat.
- Never give Alice/Yandex direct production, broker, Railway deploy, or trading authority.
- Review and production remain separate systems.

## Architecture rule
The v11 architecture is frozen unless a reproducible BLOCKER/MAJOR defect is found.
Preference, style, or speculative improvements do not reopen architecture consensus.

## Calibration rule
CAL_V1 remains NOT_FOR_PRODUCTION until its defined calibration and shadow criteria are satisfied.
