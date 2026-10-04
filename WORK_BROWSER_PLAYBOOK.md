# WORK BROWSER PLAYBOOK

## Objective
Operate the Strategy Council review loop without Lesha relaying messages.

## Browser workflow
1. Open the Yandex/Alice web chat in the Work browser.
2. If authentication is required, pause and ask Lesha only for the minimum interactive step needed (login/2FA confirmation). Never ask him to paste passwords or API keys into chat.
3. Open the dedicated Strategy Council conversation with Alice.
4. Send:
   **Алиса, синхронизируйся и дай VERDICT.json**
5. Wait for the complete answer.
6. If Alice returns prose instead of the required JSON, send:
   **Верни только валидный JSON строго по ALICE_VERDICT_TEMPLATE.json, без текста до и после.**
7. Copy the complete JSON response.
8. Validate:
   - JSON parses;
   - repository/branch are correct;
   - reviewed commit equals the intended current main commit;
   - manifest verification is explicit;
   - all file SHA values are real, not placeholders;
   - test and E2E claims are factual;
   - verdict uses the allowed enum values.
9. Save the verdict as:
   `verdicts/alice_<YYYYMMDDTHHMMSSZ>_<short_commit>.json`
10. Commit it to GitHub.
11. Continue only after the verdict is archived.

## Failure handling
- Login/2FA prompt: ask Lesha to complete only that step.
- Wrong chat: stop and select the dedicated Strategy Council Alice chat.
- No access to repository: verify public GitHub access first.
- Hash mismatch: treat as BLOCK and do not continue.
- Invalid JSON twice: stop and ask Lesha only if the browser session itself is unusable.
