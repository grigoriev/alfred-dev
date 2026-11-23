---
name: pr-workflow
description: "Create complete pull requests with description, labels and reviewers. Triggers: создать PR, pull request, открыть PR."
disable-model-invocation: true
---

# Creating complete pull requests

Communicate with the user in Russian.

## Summary

This skill guides you from checking the changes to assigning reviewers. A PR is not only a merge mechanism. It is a message that tells reviewers what changed, why, and how to verify it.

Goal: any team member can understand the PR before opening the diff, without reading every line.

## Process

1. **Check the state of changes.** Run `git diff` and `git status` to confirm the uncommitted changes match what goes into the PR. If there are uncommitted changes, ask the user whether to include them or leave them out.

2. **Check the branch.** Make sure the work is on a feature or fix branch, not directly on main. If there is no branch, create one with a descriptive name: `feature/short-name` or `fix/bug-description`.

3. **Write the title.** Keep it under 70 characters and describe the change clearly. Recommended format: `тип: краткое описание`. Examples:

   - `feat: добавить фильтр поиска по дате`
   - `fix: исправить расчёт НДС в счетах`
   - `refactor: вынести логику валидации в отдельный модуль`

4. **Write the description.** Use this standard structure:

   ```markdown
   ## Резюме
   - [1-3 пункта: что меняется и почему]

   ## Мотивация
   [Почему это изменение необходимо. Дать ссылку на issue, если он есть.]

   ## План тестирования
   - [ ] [Конкретные шаги для проверки, что изменение работает]
   - [ ] [Проверки на регрессию]

   ## Заметки для ревьюера
   [Дополнительный контекст, проектные решения, области, требующие особого внимания]
   ```

5. **Assign labels.** Label the PR by change type (`bug`, `feature`, `refactor`, `docs`) and priority, if applicable. Use `gh pr edit --add-label`.

6. **Link issues.** If the PR resolves an issue, put `Closes #XX` in the description so GitHub closes it on merge.

7. **Assign reviewers.** Pick reviewers by the area of affected code. Use `gh pr create --reviewer usuario1,usuario2`, or `gh pr edit --add-reviewer` if the PR already exists.

8. **Create the PR.** Run `gh pr create` with title, description, labels and reviewers. Check that the PR renders correctly on GitHub and CI checks start.

9. **Verify the result.** Confirm the description renders well, issue links work and reviewers got notified.

## Do NOT

- Do not include `Co-Authored-By` lines or mentions of assistants or AI tools in the PR.
- Do not create a PR without a description. A title is not enough context.
- Do not assign reviewers at random. Pick people who know the affected area.
- Do not mix unrelated changes in one PR.
