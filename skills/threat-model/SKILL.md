---
name: threat-model
description: "Use for STRIDE threat modeling: threat analysis, attack surface, attack vectors. Triggers: анализ угроз, STRIDE, поверхность атаки, векторы атаки, моделирование угроз."
---

# STRIDE threat modeling

Communicate with the user in Russian.

## Summary

This skill applies STRIDE to identify and classify security threats in a system. STRIDE is a Microsoft model that splits threats into six types and gives a systematic framework so nothing is missed.

Threat modeling works best early in development (fixes are cheaper), but it is also useful as a periodic exercise for existing systems.

## Process

1. **Identify system components.** List all significant elements:

   - Applications and services.
   - Databases and data stores.
   - APIs and external interfaces.
   - Infrastructure (servers, networks, load balancers).
   - Users and roles.
   - Data flows between components.

2. **Build a data flow diagram (DFD).** Draw data flows between components in Mermaid and mark trust boundaries. Threats usually concentrate where data crosses a trust boundary.

3. **Apply STRIDE to each component.** For each diagram element, assess six categories:

   | Category | Description | Key question |
   |-----------|----------|-----------------|
   | **S**poofing | An attacker poses as another user or system. | How is identity verified at this point? |
   | **T**ampering | An attacker changes data in transit or at rest. | How is data integrity ensured? |
   | **R**epudiation | A user denies performing an action. | Is there a reliable audit log? |
   | **I**nformation Disclosure | Sensitive data becomes visible to those who must not see it. | What data is exposed and to whom? |
   | **D**enial of Service | The system becomes unavailable to legitimate users. | Which resources can be exhausted? |
   | **E**levation of Privilege | A user gains rights they must not have. | How are access controls enforced? |

4. **Classify each threat by risk.** Use a likelihood and impact matrix:

   - **Likelihood:** high (easy to exploit, no special attacker skill needed) / medium / low (needs insider access and special knowledge).
   - **Impact:** critical (data loss, security breach) / high (service interruption) / medium (partial degradation) / low (minor inconvenience).

5. **Propose a mitigation for each threat.** Mitigations must be specific and actionable:

   - No: «улучшить безопасность».
   - Yes: «внедрить rate limiting 100 запросов/минуту на endpoint логина».

6. **Prioritize by risk/effort.** High-impact, low-effort mitigations go first. Low-impact, high-effort mitigations are documented but deferred.

7. **Document the model.** Canonical location: `docs/project/threat-model.md`.
   If the file does not exist, create it with `sync-project-docs`. Base it on real components and
   flows, not a generic list. Use `templates/threat-model.md`
   as the form. Replace `<!-- alfred-doc:scaffold -->` with
   `<!-- alfred-doc:filled -->`.

## Success criteria

- All system components are assessed against the 6 STRIDE categories.
- Threats are classified by likelihood and impact.
- Each threat has at least one proposed mitigation.
- Mitigations are prioritized by risk/effort.
- The model is in `docs/project/threat-model.md` with the `filled` marker.
- Threats and mitigations are recorded in project memory.

## Memory step

Record the identified threats and proposed mitigations in project memory with `memory_log_decision`. This tracks mitigation status across sessions and helps spot new attack surfaces as the system evolves.

## Do NOT

- Do not model threats in the abstract without knowing the real architecture. Base the model on concrete components and data flows, not a generic list.
- Do not limit the model to technical threats. Organizational threats (social engineering, physical access, insiders) also matter if the system handles sensitive data.
- Do not leave the threat model static. Review it when the architecture changes, integrations are added, or it is deployed to a new environment.
- Do not propose vague mitigations like «улучшить безопасность». Each mitigation must be specific, implementable and verifiable.
