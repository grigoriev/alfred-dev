---
name: incident-response
description: "Production incident response protocol: triage, mitigation, root cause and postmortem. Use for outages, critical errors, security incidents or service degradation. Triggers: инцидент, падение, авария, деградация сервиса, постмортем."
disable-model-invocation: true
---

# Incident response

Communicate with the user in Russian.

The user reported or found a production incident. Follow this protocol step by step, from first triage to the final postmortem.

## Summary

Production incidents need a fast but orderly response. Do not jump into the code: without triage, time goes to wrong diagnoses. Document every step and record lessons learned to reduce repeats.

## Process

### Phase 1: Triage (qa-engineer)

Use the Agent tool to start the `qa-engineer` agent with this mission:

1. Classify incident severity (P0 critical, P1 high, P2 medium, P3 low).
2. Determine impact: affected users, broken functionality, data at risk.
3. Collect evidence: logs, traces, screenshots, error messages.
4. Determine whether an immediate workaround exists.

**Artifact:** triage report with severity, impact and evidence.

### Phase 2: Mitigation (senior-dev)

If triage shows P0 or P1, mitigate immediately:

1. Apply the workaround if one exists (rollback, feature flag, traffic redirect).
2. If there is no workaround, write a minimal hotfix with a regression test.
3. Deploy the mitigation and check that the impact decreases.

**Artifact:** commit with the mitigation and regression test.

### Phase 3: Root cause analysis (senior-dev + security-officer)

When the impact is mitigated, investigate the root cause:

1. Trace the chain of events from trigger to failure.
2. Identify the root cause (not the symptom).
3. If the incident has a security component, security-officer audits the chain.
4. Record the root cause as a decision in project memory.

**Artifact:** RCA (Root Cause Analysis) document.

### Phase 4: Postmortem

Produce a full postmortem report:

1. Incident timeline (when detected, when mitigated, when resolved).
2. Confirmed root cause.
3. Corrective actions with owner and due date.
4. Preventive actions to stop recurrence.
5. Lessons learned.

**Artifact:** postmortem document in Markdown.

## Postmortem format

```markdown
# Постмортем: [название инцидента]

**Дата:** YYYY-MM-DD
**Серьёзность:** P0/P1/P2/P3
**Длительность:** X часов/минут
**Влияние:** [описание влияния]

## Хронология
- HH:MM - [событие]
- HH:MM - [событие]

## Первопричина
[Подробное объяснение]

## Корректирующие действия
- [ ] [действие] - Ответственный: [имя] - Дата: YYYY-MM-DD

## Превентивные действия
- [ ] [действие] - Ответственный: [имя] - Дата: YYYY-MM-DD

## Извлечённые уроки
1. [урок]
```

## Success criteria

- The incident has a severity based on objective criteria.
- Mitigation happens before root cause investigation (put out the fire first).
- An RCA document exists and identifies the real root cause, not only the symptom.
- The postmortem is complete: timeline, corrective and preventive actions.
- Lessons learned are recorded in project memory.
- Corrective actions have an owner and a due date.

## Do NOT

- **Do not skip triage to go straight to the code.** Without triage, time goes to wrong hypotheses, and changes can make the situation worse. Triage structures the response and sets priorities.
- **Do not close an incident without a postmortem.** Even if the fix is trivial, documenting what broke and why prevents repeats and builds institutional knowledge.
- **Do not blame people in the postmortem.** Focus on processes and systems, not individuals. Ask "what in the system allowed this error", not "who made the error". A punitive postmortem destroys trust and discourages transparency.
