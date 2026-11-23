---
name: evaluate-dependency
description: "Use before adopting a new dependency: package audit, license, CVE, transitive dependencies, bundle size, npm install, pip, cargo add. Triggers: аудит пакета, лицензия, транзитивные зависимости, размер bundle, новая зависимость."
---

# Dependency evaluation

Communicate with the user in Russian.

## Summary

Before you add a package, evaluate it and record the verdict in
`docs/project/dependencies.md`. The helper can create a scaffold; you write the row.

## Process

1. Make sure the package is not in the registry yet.

2. Collect verifiable data (lockfile, registry, advisory):

   - name and exact version
   - approximate weight or bundle impact
   - last release and maintenance
   - license and compatibility with the project
   - known CVEs or «не найдено» (with source)
   - number of transitive dependencies
   - a lighter or native alternative

3. Verdict: `ОДОБРИТЬ`, `ОТКЛОНИТЬ` or `ОДОБРИТЬ С УСЛОВИЯМИ`.

4. Add or update the row in `docs/project/dependencies.md`. If the file was a
   scaffold and now has a real evaluation, replace
   `<!-- alfred-doc:scaffold -->` with `<!-- alfred-doc:filled -->`.

5. If the verdict is not `ОДОБРИТЬ`, do not install the package. Suggest an alternative.

## Success criteria

- The row exists with version, license and verdict.
- A CVE "not applicable" comes with a technical reason, not a guess.
- The registry lives in the repository, not only in the chat.

## Do NOT

- Do not evaluate from memory without checking the lockfile or manifest.
- Do not approve a dependency on "we all use it already" without data.
- Do not leave licenses unknown without saying so.
