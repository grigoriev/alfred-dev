---
name: compliance-check
description: "Use to check compliance with GDPR (RGPD), NIS2 and CRA. Triggers: проверить GDPR, RGPD, нормативное соответствие, compliance, NIS2, CRA, Cyber Resilience Act, защита данных, европейское регулирование."
---

# Compliance check

Communicate with the user in Russian.

## Summary

Assess the project against three EU frameworks: GDPR (RGPD, data protection), NIS2 (infrastructure cybersecurity) and CRA (Cyber Resilience Act, security of products with digital elements). Output: a compliance report with the current project state for each requirement and the actions needed to comply.

This is a technical assessment that finds gaps and directs development work. It is not a legal opinion.

## Process

1. **Identify which regulations apply.** Not every project falls under all three:

   - **GDPR (RGPD):** applies if the software processes personal data of people in the EU.
   - **NIS2:** applies if the organization works in critical sectors or provides digital services.
   - **CRA:** applies to products with digital elements placed on the EU market (including open source software with commercial use).

2. **GDPR (RGPD) checklist:**

   - [ ] Legal basis for processing (consent, legitimate interest, contract, etc.).
   - [ ] Data minimization: collect only strictly necessary data.
   - [ ] Impact assessment (DPIA) for high-risk processing.
   - [ ] Record of processing activities is documented.
   - [ ] Right of access: the user can request their data.
   - [ ] Right to rectification: the user can correct their data.
   - [ ] Right to erasure: the user can request deletion of their data.
   - [ ] Portability: the user can export their data in a standard format.
   - [ ] Breach notification within 72 hours.
   - [ ] Personal data encrypted in transit and at rest.
   - [ ] Data protection officer (DPO) appointed, if applicable.

3. **NIS2 checklist:**

   - [ ] Cybersecurity risk management is documented.
   - [ ] Information security policy approved by management.
   - [ ] Incident notification: early warning within 24 h, full report within 72 h.
   - [ ] Supply chain security: supplier assessment.
   - [ ] Governance: cybersecurity responsibilities assigned.
   - [ ] Business continuity and disaster recovery plan.
   - [ ] Staff cybersecurity training.
   - [ ] Vulnerability and update management.
   - [ ] Multi-factor authentication for critical access.

4. **CRA (Cyber Resilience Act) checklist:**

   - [ ] SBOM (Software Bill of Materials) generated and maintained.
   - [ ] Security updates available for the whole lifecycle.
   - [ ] Secure by default design.
   - [ ] Product technical documentation available.
   - [ ] Vulnerability management with a reporting process.
   - [ ] ENISA notified of actively exploited vulnerabilities within 24 h.
   - [ ] Conformity assessment (self-assessment or certification, depending on category).
   - [ ] CE marking for applicable products.

5. **Write the living register.** Do not leave the result only in chat.
   Canonical location: `docs/project/compliance.md`. If the file does not exist, create
   it first with `python3 .claude/alfred-continuity.py sync-project-docs "$PWD"`.
   Use `templates/compliance.md` as the form. For each control: status,
   evidence (code path, test or configuration) and actions. Without evidence,
   do not set `compliant`. Replace `<!-- alfred-doc:scaffold -->` with
   `<!-- alfred-doc:filled -->`.

## Success criteria

- The regulations that apply to the project are identified.
- Each checklist is checked item by item, with the status documented.
- Required actions are prioritized by risk and impact.
- The report is actionable: a developer can take any action and do it.
- The register is in `docs/project/compliance.md` with the `filled` marker.
- The compliance state is recorded in project memory.

## Final step: record in memory

Record the compliance state in project memory with `memory_log_decision` to track it across sessions. This lets you compare compliance over time and detect regulatory regressions.

## Version note

This skill is based on GDPR (RGPD, Regulation 2016/679), NIS2 (Directive 2022/2555) and CRA (Regulation 2024/2847). Before you treat the assessment as valid, check whether later updates to these documents are in force.

## Do NOT

- Do not treat this assessment as a substitute for legal advice. It finds technical gaps. Legal decisions need a qualified professional.
- Do not mark a requirement as met without technical evidence (code, configuration, verifiable documentation).
- Do not ignore CRA because the software is open source. CRA applies to OSS with commercial use. The exemption covers only free software without profit motive and without commercial activity.
- Do not treat the assessment as complete until you document the non-applicable requirements and why they do not apply.
