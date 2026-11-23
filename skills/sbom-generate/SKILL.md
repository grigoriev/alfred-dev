---
name: sbom-generate
description: "Use to generate a Software Bill of Materials for CRA compliance: SBOM, component inventory, CycloneDX, SPDX, supply chain. Triggers: SBOM, инвентаризация компонентов, цепочка поставок, соответствие CRA."
---

# SBOM generation (Software Bill of Materials)

Communicate with the user in Russian.

## Summary

This skill builds a complete inventory of all software components in the project, both direct and transitive dependencies. An SBOM is required by the EU Cyber Resilience Act (CRA) and is a recommended supply chain security practice.

An SBOM lets you quickly answer questions like «используем ли мы версию, затронутую этой уязвимостью?» without inspecting each project by hand.

## Process

1. **Identify the ecosystem and dependency sources.** Find all lock files and manifests:

   - Node.js: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`.
   - Python: `requirements.txt`, `Pipfile.lock`, `poetry.lock`.
   - Rust: `Cargo.lock`.
   - Go: `go.sum`.
   - Java: `pom.xml`, `build.gradle`.
   - PHP: `composer.lock`.

2. **List direct dependencies.** For each, record:

   - Package name.
   - Exact installed version.
   - License.
   - Supplier or author.
   - Repository URL.
   - Verification hash (if the lock file has one).

3. **List transitive dependencies.** Repeat for all dependencies of dependencies. Transitive ones are usually the majority and the hardest to track.

4. **Include components not managed by package managers.** Some components are added by hand:

   - Libraries copied directly (vendoring).
   - Third-party scripts loaded from a CDN.
   - Precompiled binaries.
   - Base operating system components (especially important in Docker containers).

5. **Produce a standard format.** Use one of the two industry formats:

   - **CycloneDX:** JSON or XML, preferred by OWASP. Lighter and security-focused.
   - **SPDX:** ISO standard (ISO/IEC 5962:2021). Richer license information.

   If the ecosystem has automated tools (such as `cyclonedx-npm`, `syft`, `cdxgen`), use them. If not, produce it by hand with the `templates/sbom.md` template.

6. **Check completeness.** Compare the SBOM with the lock file to make sure no dependency is missing. Check that all licenses are identified (none "unknown").

7. **Sign or version the SBOM.** Tie the SBOM to a specific software version (Git tag, package version). Regenerate the SBOM on every release.

## Success criteria

- The SBOM includes all direct and transitive dependencies.
- Each component has: name, version, license, supplier and hash.
- The format is CycloneDX or SPDX compatible.
- No license is marked "unknown" without justification.
- The SBOM is tied to a specific software version.
- Completeness is checked against the project lock file.
