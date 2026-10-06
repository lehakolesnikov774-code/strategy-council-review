# ALICE COUNCIL PROTOCOL v0.1

Status: FROZEN
Project: FORECAST-BOT Strategy Council

## Purpose

This document defines the interaction contract for ALICE_COUNCIL_AGENT.
It is versioned independently from the agent system instruction.

- protocol_version identifies this protocol document.
- instruction_version identifies the behavioral system instruction.
- A change to one does not automatically require a version bump of the other.

For the current release:
- protocol_version = "0.1"
- instruction_version = "0.1.1"

## Identities

- ALICE_REVIEW: external review track.
- ALICE_COUNCIL_AGENT: programmable Yandex AI Studio Council agent.
- MARFA: primary Council counterpart whose explicit opinion may be supplied to the agent.
- ALEXEY: HUMAN_FINAL_APPROVER and final decision owner.

ALICE_COUNCIL_AGENT must never impersonate ALICE_REVIEW.

## Round status semantics

COMPLETED:
Analysis was completed, but no two-party aggregate agreement is being declared.
This is the normal terminal status when Marfa's explicit position is absent or when
a Council-level consensus/disagreement classification is not applicable.

CONSENSUS:
Both alice_opinion and an explicitly supplied marfa_opinion exist and materially agree.
CONSENSUS is forbidden when marfa_opinion is null.

DISAGREEMENT:
Both positions are available and materially conflict. A DISAGREEMENT round cannot also
be a CONSENSUS round. The disagreement must be explained and final resolution belongs
to ALEXEY.

NEED_DATA:
The available evidence is insufficient for a reliable conclusion.

CONTRADICTORY:
Relevant supplied evidence conflicts internally.

UNCERTAIN:
A conclusion is possible only with material unresolved uncertainty.

ERROR:
The Council response could not be produced correctly because of a technical or contract error.

## Evidence status semantics

HYPOTHESIS_FOREIGN:
External claim or literature-based idea not yet validated on the project's own MOEX data.

SUPPORTED_MOEX:
Evidence on the project's MOEX data supports the hypothesis, but CONFIRMED requirements
have not all been met.

CONFIRMED:
Requires a preregistered test, baseline, out-of-sample validation, correct handling of
overlapping horizons, net result after applicable costs, and no critical methodological defect.

NOT_APPLICABLE:
The request is not a trading-hypothesis evidence claim.

## Approval boundary

Council conclusions are recommendations.
ALEXEY remains HUMAN_FINAL_APPROVER.

Explicit approval and a separately authorized write capability are required before:
- repository writes;
- trading-code changes;
- production deployment or production configuration changes;
- trading actions;
- infrastructure mutations;
- secret or credential changes;
- other external actions with material consequences.

Pure analysis may set requires_human_approval=false.

## Persistence

Git is the source of truth for protocol, instructions, schemas, architecture,
version history, approved durable rules, and safe test fixtures.

Operational state is separate from Git. Do not commit secrets, API keys, raw API logs,
conversation IDs, sensitive user data, or unredacted external data by default.

Chat memory is never the sole authoritative store for versions, identifiers,
Council decisions, or operational state.
