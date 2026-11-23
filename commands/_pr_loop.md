---
description: "Внутренний общий протокол PR-цикла: ревью людей и ИИ, Greptile, SonarCloud, конфликты и автоматический мерж по зелёному."
---

# PR loop protocol

Communicate with the user in Russian.

This file defines how Alfred drives a pull request to merge. `/alfred-dev:pr` uses it, and so do all flows that end with a PR: `feature`, `fix` and `quick`. Any change here affects all of them.

## Merge conditions

The PR merges automatically, without confirmation, only when all conditions are met:

1. All review threads are resolved, no review requests changes. Human and AI comments are handled the same way. Human approval is not required.
2. All CI checks are green.
3. Greptile: confidence 5/5, or 4/5 if Greptile states explicitly what exactly it cannot check.
4. SonarCloud: quality gate green, 0 open issues, 100% coverage of new code.
5. No conflicts with the base branch.

The helper decides, not you:

```bash
python3 .claude/alfred-continuity.py pr-status "$PWD" --pr <номер>
```

First line of the output: the `PR_STATUS_<ВЕРДИКТ>` marker. Act only on it.

## Step 1 -- Open the PR

If the current branch has no PR yet:

1. Check that you are not on the base branch. If you are, create a `type/description` branch.
2. Commit all work. Run the project tests. Do not open a PR with red tests.
3. Push the branch: `git push -u origin <ветка>`. Never use `--force`.
4. Create the PR per the `pr-workflow` skill (`gh pr create`). Remember the PR number.

If `gh` in a fork targets upstream, run `gh repo set-default <owner>/<repo>`.

## Step 2 -- Loop

Repeat until the helper returns `PR_STATUS_MERGE`, `PR_STATUS_DONE` or `PR_STATUS_NEEDS_USER`. Count fix rounds: each `FIX` or `CONFLICT` is one round. Limit: 5 rounds.

### `PR_STATUS_WAIT`

Checks or reviews are not ready yet. Waiting does not count as a round.

- If the output has an «Действие» section with `greptile review`, run the Greptile CLI review from the repository root: `greptile review --agent --json`. In the PR loop, do this without separate confirmation: the user enabled the loop, and the review is part of it. CTO fills this role.
- Then wait for checks: `gh pr checks <номер> --watch --interval 30`.
- Call `pr-status` again.
- If waiting takes more than 60 minutes, stop and tell the user what you are waiting for.

### `PR_STATUS_CONFLICT`

Activate `senior-dev`:

1. `git fetch origin` and `git merge origin/<база>` into the PR branch. Do not rebase or force push.
2. Resolve each conflict so that the intent of both sides is kept. If the meaning of a conflict is unclear, stop and ask the user.
3. Run all project tests. Commit the merge and push.
4. Call `pr-status` again.

### `PR_STATUS_FIX`

Activate `senior-dev` and pass it the full «Что исправить» and «Блокеры» sections.

- **Review thread** (human or AI): fix the comment, test first, then code. If the comment is factually wrong, reply in the thread with evidence. Never resolve a thread without a fix or a reply.
- **Failed check**: read the log (`gh run view <id> --log-failed`) and fix the cause. Do not disable or weaken the check.
- **Greptile comment**: fix it the same way as a thread.
- **Greptile below 5/5 without separate comments**: read the confidence rationale and remove the named risks.
- **SonarCloud issue**: fix each one. Do not mark an issue as false positive without an explicit user decision.
- **Coverage below 100%**: add tests for uncovered lines of new code.

After the fixes:

1. Run the project tests locally. Commit and push (without `--force`).
2. Reply «Исправлено в `<sha>`» to each fixed thread and resolve it:
   `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<id>"}) { thread { isResolved } } }'`
3. Call `pr-status` again. After a push a new Greptile review is needed: the helper asks for it.

### `PR_STATUS_MERGE`

Merge yourself, without asking:

1. Get the allowed methods: `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`.
2. Prefer squash: `gh pr merge <номер> --squash --delete-branch`. If squash is not allowed, use an allowed method.
3. Never use `--admin` and never bypass branch protection.
4. Tell the user: the PR, final Greptile and SonarCloud scores, number of rounds.

### `PR_STATUS_DONE`

The PR is already merged or closed. Say so and stop.

### `PR_STATUS_NEEDS_USER`

Stop. Show the blockers from the helper output and ask the user what to do. Examples: SonarCloud not configured, `gh` not authenticated, PR in draft.

### Round limit

If the verdict is not `MERGE` after 5 rounds, stop. Show the last status and what is still open. Ask the user whether to continue.

## Prohibitions

- Do not merge until the helper returns `PR_STATUS_MERGE`.
- Do not use `--force`, `--admin` and `--no-verify`.
- Do not weaken SonarCloud thresholds, CI rules or test checks to pass a gate.
- Do not resolve a thread without a fix or a substantive reply.
- Do not present waiting or an assumption as a verified result.
