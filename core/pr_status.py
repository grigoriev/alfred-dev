#!/usr/bin/env python3
"""Collect the review state of a pull request and decide the next step.

The PR loop of Alfred merges a pull request only when every reviewer is
satisfied and every quality gate is green:

- every review thread is resolved and no review requests changes;
- every CI check passed;
- Greptile gives 5/5, or 4/5 with a stated reason what it cannot verify;
- SonarCloud: quality gate passed, 0 open issues, 100% coverage of new code;
- the branch has no merge conflict with its base.

Data comes from the GitHub CLI (``gh``) and the SonarCloud web API. The gate
decision is plain code, so the model does not judge "good enough" by eye.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_ROUNDS = 5
REQUIRED_COVERAGE = 100.0
SONAR_HOST = "https://sonarcloud.io"

VERDICT_MERGE = "merge"
VERDICT_FIX = "fix"
VERDICT_CONFLICT = "conflict"
VERDICT_WAIT = "wait"
VERDICT_NEEDS_USER = "needs_user"
VERDICT_DONE = "done"

# How Greptile counts for the merge (config key pr_loop.greptile).
GREPTILE_REQUIRED = "required"
GREPTILE_OPTIONAL = "optional"
GREPTILE_OFF = "off"
GREPTILE_MODES = (GREPTILE_REQUIRED, GREPTILE_OPTIONAL, GREPTILE_OFF)
_MODE_ALIASES = {"false": GREPTILE_OFF, "no": GREPTILE_OFF, "true": GREPTILE_REQUIRED,
                 "yes": GREPTILE_REQUIRED, "on": GREPTILE_REQUIRED}

_CONFIDENCE_RE = re.compile(r"confidence(?:\s+score)?\s*[:\-]?\s*\**\s*(\d)\s*/\s*5", re.IGNORECASE)
_UNVERIFIABLE_RE = re.compile(
    r"[^.\n]*("
    r"cannot|can't|can not|could not|couldn't|unable to|not able to|no way to|"
    r"unverified|not verified|without running|without access|"
    r"не может|не могу|не удалось|невозможно|не провер"
    r")[^.\n]*",
    re.IGNORECASE,
)
_PASSING_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_PENDING_STATES = {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING", "REQUESTED"}

Runner = Callable[[List[str]], str]
Fetcher = Callable[[str], Dict[str, Any]]


# --- Data collection -------------------------------------------------------


def _run_gh(args: List[str], cwd: Optional[str] = None) -> str:
    result = subprocess.run(
        ["gh", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"gh {' '.join(args)} failed")
    return result.stdout


def _fetch_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get("SONAR_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))


_PR_FIELDS = ",".join([
    "number", "url", "state", "isDraft", "mergeable", "mergeStateStatus",
    "headRefName", "headRefOid", "baseRefName", "reviewDecision",
    "statusCheckRollup", "comments", "reviews", "commits",
])

_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 1) { nodes { author { login } body url } }
        }
      }
    }
  }
}
"""


def collect_github(project_dir: str, pr: Optional[str], run: Optional[Runner] = None) -> Dict[str, Any]:
    """Read the PR, its review threads and the repository name through gh."""
    run = run or (lambda args: _run_gh(args, cwd=project_dir))
    view_args = ["pr", "view"] + ([str(pr)] if pr else []) + ["--json", _PR_FIELDS]
    data = json.loads(run(view_args))
    # Take the repository from the PR URL: in a fork, `gh repo view` may
    # resolve to the parent repository.
    match = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/pull/\d+", data.get("url", ""))
    if match:
        owner, name = match.group(1), match.group(2)
    else:
        repo = json.loads(run(["repo", "view", "--json", "owner,name"]))
        owner = (repo.get("owner") or {}).get("login", "")
        name = repo.get("name", "")
    threads_raw = json.loads(run([
        "api", "graphql",
        "-f", f"query={_THREADS_QUERY}",
        "-F", f"owner={owner}",
        "-F", f"name={name}",
        "-F", f"number={data['number']}",
    ]))
    nodes = (
        threads_raw.get("data", {}).get("repository", {}).get("pullRequest", {})
        .get("reviewThreads", {}).get("nodes", [])
    )
    data["reviewThreads"] = nodes
    data["repository"] = f"{owner}/{name}"
    return data


def _run_greptile(args: List[str], cwd: Optional[str] = None) -> Tuple[int, str]:
    result = subprocess.run(
        ["greptile", *args, "--agent"],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode, result.stdout


GreptileRunner = Callable[[List[str]], Tuple[int, str]]


def collect_greptile_cli(project_dir: str, head: str, run: Optional[GreptileRunner] = None) -> Dict[str, Any]:
    """Read the Greptile CLI review of the head commit, if one exists."""
    run = run or (lambda args: _run_greptile(args, cwd=project_dir))
    try:
        code, out = run(["review", "status", "--commit", head, "--json"])
        status = json.loads(out.strip().splitlines()[0]) if out.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return {"status": "unavailable"}
    if code == 3 or status.get("status") in {"running", "in_progress", "queued", "pending"}:
        return {"status": "running"}
    if status.get("confidence") is None or not status.get("runId"):
        return {"status": "missing"}
    review: Dict[str, Any] = {}
    try:
        code, out = run(["review", "show", str(status["runId"]), "--json"])
        review = json.loads(out) if out.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        review = {}
    return {
        "status": "ok",
        "confidence": int(status["confidence"]),
        "reasoning": review.get("confidenceReasoning") or "",
        "comments": review.get("comments") or [],
        "run_id": status["runId"],
    }


def find_sonar_project_key(project_dir: str) -> str:
    """Find the SonarCloud project key in the usual project files."""
    patterns: List[Tuple[str, re.Pattern]] = [
        ("sonar-project.properties", re.compile(r"^\s*sonar\.projectKey\s*=\s*(\S+)", re.M)),
        ("pom.xml", re.compile(r"<sonar\.projectKey>\s*([^<\s]+)\s*</sonar\.projectKey>")),
        ("build.gradle", re.compile(r"""property\s*\(?\s*["']sonar\.projectKey["']\s*,\s*["']([^"']+)""")),
        ("build.gradle.kts", re.compile(r"""property\s*\(\s*"sonar\.projectKey"\s*,\s*"([^"]+)""")),
    ]
    for relative, pattern in patterns:
        path = os.path.join(project_dir, relative)
        if os.path.isfile(path):
            match = pattern.search(open(path, encoding="utf-8", errors="replace").read())
            if match:
                return match.group(1)
    workflows = os.path.join(project_dir, ".github", "workflows")
    if os.path.isdir(workflows):
        flag = re.compile(r"sonar\.projectKey[=:]\s*['\"]?([\w.\-:]+)")
        for name in sorted(os.listdir(workflows)):
            if name.endswith((".yml", ".yaml")):
                match = flag.search(open(os.path.join(workflows, name), encoding="utf-8", errors="replace").read())
                if match:
                    return match.group(1)
    return ""


def collect_sonar(project_key: str, pr_number: int, fetch: Optional[Fetcher] = None) -> Dict[str, Any]:
    """Read the PR quality gate, open issues and new-code coverage."""
    fetch = fetch or _fetch_json
    if not project_key:
        return {"status": "not_configured"}
    query = urllib.parse.urlencode({"projectKey": project_key, "pullRequest": pr_number})
    try:
        gate = fetch(f"{SONAR_HOST}/api/qualitygates/project_status?{query}")
        issues = fetch(
            f"{SONAR_HOST}/api/issues/search?"
            + urllib.parse.urlencode({
                "componentKeys": project_key, "pullRequest": pr_number,
                "resolved": "false", "ps": 50,
            })
        )
        measures = fetch(
            f"{SONAR_HOST}/api/measures/component?"
            + urllib.parse.urlencode({
                "component": project_key, "pullRequest": pr_number,
                "metricKeys": "new_coverage,new_lines_to_cover",
            })
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "no_analysis", "project_key": project_key}
        return {"status": "error", "project_key": project_key, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"status": "error", "project_key": project_key, "error": str(exc)}

    values = {
        item.get("metric"): _measure_value(item)
        for item in measures.get("component", {}).get("measures", [])
    }
    return {
        "status": "ok",
        "project_key": project_key,
        "gate": gate.get("projectStatus", {}).get("status", "NONE"),
        "issues_total": int(issues.get("total", 0)),
        "issues": [
            {"key": issue.get("key"), "rule": issue.get("rule"), "message": issue.get("message"),
             "component": issue.get("component"), "line": issue.get("line")}
            for issue in issues.get("issues", [])[:50]
        ],
        "new_coverage": _to_float(values.get("new_coverage")),
        "new_lines_to_cover": _to_float(values.get("new_lines_to_cover")),
    }


def _measure_value(item: Dict[str, Any]) -> Any:
    periods = item.get("periods") or []
    if periods:
        return periods[0].get("value")
    if "period" in item:
        return item["period"].get("value")
    return item.get("value")


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- Evaluation ------------------------------------------------------------


def parse_greptile(github: Dict[str, Any]) -> Dict[str, Any]:
    """Find the latest Greptile summary and read its confidence score."""
    head = github.get("headRefOid", "")
    entries: List[Dict[str, Any]] = []
    for review in github.get("reviews") or []:
        entries.append({
            "author": (review.get("author") or {}).get("login", ""),
            "body": review.get("body") or "",
            "at": review.get("submittedAt") or "",
            "commit": (review.get("commit") or {}).get("oid", ""),
        })
    for comment in github.get("comments") or []:
        entries.append({
            "author": (comment.get("author") or {}).get("login", ""),
            "body": comment.get("body") or "",
            "at": comment.get("updatedAt") or comment.get("createdAt") or "",
            "commit": "",
        })
    scored = [
        entry for entry in entries
        if "greptile" in entry["author"].lower() and _CONFIDENCE_RE.search(entry["body"])
    ]
    if not scored:
        return {"status": "missing"}
    latest = max(scored, key=lambda entry: entry["at"])
    confidence = int(_CONFIDENCE_RE.search(latest["body"]).group(1))
    explanation = ""
    if confidence == 4:
        match = _UNVERIFIABLE_RE.search(latest["body"])
        explanation = match.group(0).strip() if match else ""
    head_time = _head_commit_time(github)
    stale = bool(
        (latest["commit"] and head and latest["commit"] != head)
        or (not latest["commit"] and head_time and latest["at"] and latest["at"] < head_time)
    )
    return {
        "status": "ok",
        "confidence": confidence,
        "explanation": explanation,
        "stale": stale,
        "at": latest["at"],
    }


_CLAUDE_LOGINS = {"claude", "claude[bot]"}


def claude_review_status(github: Dict[str, Any]) -> str:
    """Return ok, stale or missing for the Claude Code review of the head commit."""
    head = github.get("headRefOid", "")
    head_time = _head_commit_time(github)
    reviews = [r for r in github.get("reviews") or [] if _is_claude_entry(r)]
    comments = [c for c in github.get("comments") or [] if _is_claude_entry(c)]
    if any(_review_is_current(r, head, head_time) for r in reviews):
        return "ok"
    if any(_not_older(c.get("updatedAt") or c.get("createdAt"), head_time) for c in comments):
        return "ok"
    return "stale" if reviews or comments else "missing"


def _review_is_current(review: Dict[str, Any], head: str, head_time: str) -> bool:
    commit = (review.get("commit") or {}).get("oid", "")
    if commit:
        return commit == head
    return _not_older(review.get("submittedAt"), head_time)


def _claude_checks(github: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in _latest_checks(github.get("statusCheckRollup") or [])
            if "claude-review" in _check_name(c).lower()]


def needs_greptile_cli(github: Dict[str, Any], mode: str) -> bool:
    """True when the Greptile CLI review decides: required mode, or optional without Claude."""
    bot = parse_greptile(github)
    if bot["status"] == "ok" and not bot.get("stale"):
        return False
    if mode == GREPTILE_REQUIRED:
        return True
    return mode == GREPTILE_OPTIONAL and _no_claude_workflow(github)


def _no_claude_workflow(github: Dict[str, Any]) -> bool:
    """True when the PR shows no sign of the Claude Code review: no review, no comment, no check."""
    return claude_review_status(github) == "missing" and not _claude_checks(github)


def _claude_review_running(github: Dict[str, Any]) -> bool:
    """True while the Claude Code review workflow of the PR still runs."""
    return any(not _check_outcome(check) for check in _claude_checks(github))


def _is_claude_entry(item: Dict[str, Any]) -> bool:
    login = ((item.get("author") or {}).get("login") or "").lower()
    return login in _CLAUDE_LOGINS and bool((item.get("body") or "").strip())


def _not_older(at: Optional[str], head_time: str) -> bool:
    return not head_time or bool(at and at >= head_time)


def _head_commit_time(github: Dict[str, Any]) -> str:
    commits = github.get("commits") or []
    if not commits:
        return ""
    last = commits[-1]
    return last.get("committedDate") or last.get("authoredDate") or ""


def _check_name(check: Dict[str, Any]) -> str:
    return check.get("name") or check.get("context") or "check"


def evaluate(github: Dict[str, Any], sonar: Dict[str, Any],
             greptile_cli: Optional[Dict[str, Any]] = None,
             greptile_mode: str = GREPTILE_REQUIRED) -> Dict[str, Any]:
    """Decide the next step of the PR loop from collected data.

    greptile_mode: required needs a current Greptile score; optional checks a
    current Greptile score if there is one and otherwise accepts the Claude
    Code review of the head commit; off ignores Greptile and needs that review.
    """
    if greptile_mode not in GREPTILE_MODES:
        greptile_mode = GREPTILE_REQUIRED
    state = github.get("state", "")
    if state in {"MERGED", "CLOSED"}:
        return {"verdict": VERDICT_DONE, "state": state, "blockers": [], "fix_items": [], "wait_items": []}

    blockers: List[str] = []
    fix_items: List[Dict[str, Any]] = []
    wait_items: List[str] = []
    actions: List[str] = []
    conflict = github.get("mergeable") == "CONFLICTING" or github.get("mergeStateStatus") == "DIRTY"

    _evaluate_threads(github, blockers, fix_items)
    _evaluate_checks(github, fix_items, wait_items)
    greptile, ai_review = _evaluate_ai_review(github, greptile_cli, greptile_mode,
                                              fix_items, wait_items, actions)
    _evaluate_greptile_score(greptile, blockers)
    needs_user = _evaluate_sonar(sonar, blockers, fix_items, wait_items)
    if needs_user:
        verdict = VERDICT_NEEDS_USER
        blockers = [needs_user]
    elif conflict:
        verdict = VERDICT_CONFLICT
    elif fix_items or blockers:
        verdict = VERDICT_FIX
    elif wait_items:
        verdict = VERDICT_WAIT
    elif github.get("isDraft"):
        verdict = VERDICT_NEEDS_USER
        blockers.append("PR в статусе draft.")
    else:
        verdict = VERDICT_MERGE
    result = _result(verdict, blockers, fix_items, wait_items, greptile, sonar, conflict)
    result["actions"] = actions
    result["ai_review"] = ai_review
    result["greptile_mode"] = greptile_mode
    return result


def _evaluate_threads(github: Dict[str, Any], blockers: List[str], fix_items: List[Dict[str, Any]]) -> None:
    for thread in github.get("reviewThreads") or []:
        if thread.get("isResolved"):
            continue
        first = ((thread.get("comments") or {}).get("nodes") or [{}])[0]
        fix_items.append({
            "kind": "thread",
            "id": thread.get("id"),
            "path": thread.get("path"),
            "line": thread.get("line"),
            "author": (first.get("author") or {}).get("login", ""),
            "body": (first.get("body") or "")[:500],
            "url": first.get("url", ""),
        })
    if github.get("reviewDecision") == "CHANGES_REQUESTED":
        blockers.append("Есть ревью с запросом изменений.")


def _latest_checks(checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the newest run per check: a rerun supersedes a cancelled or failed one."""
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for check in checks:
        key = (check.get("workflowName") or "", _check_name(check))
        stamp = check.get("startedAt") or check.get("createdAt") or ""
        current = latest.get(key)
        if current is None or stamp >= (current.get("startedAt") or current.get("createdAt") or ""):
            latest[key] = check
    return list(latest.values())


def _check_outcome(check: Dict[str, Any]) -> str:
    """Return the upper-case outcome, or an empty string while the check runs."""
    if "status" in check:
        # CheckRun: status shows progress, conclusion shows the result.
        if (check.get("status") or "").upper() != "COMPLETED":
            return ""
        return (check.get("conclusion") or "").upper()
    # StatusContext: one state field.
    outcome = (check.get("state") or "").upper()
    return "" if outcome in _PENDING_STATES else outcome


def _evaluate_checks(github: Dict[str, Any], fix_items: List[Dict[str, Any]], wait_items: List[str]) -> None:
    for check in _latest_checks(github.get("statusCheckRollup") or []):
        outcome = _check_outcome(check)
        if not outcome:
            wait_items.append(f"Check `{_check_name(check)}` ещё выполняется.")
        elif outcome not in _PASSING_CONCLUSIONS:
            fix_items.append({"kind": "check", "name": _check_name(check), "outcome": outcome,
                              "url": check.get("detailsUrl") or check.get("targetUrl") or ""})


def _evaluate_ai_review(github: Dict[str, Any], greptile_cli: Optional[Dict[str, Any]], mode: str,
                        fix_items: List[Dict[str, Any]], wait_items: List[str],
                        actions: List[str]) -> Tuple[Dict[str, Any], str]:
    """Return the Greptile data and which AI review counts: greptile, claude or empty."""
    if mode == GREPTILE_REQUIRED:
        greptile = _evaluate_greptile_required(github, greptile_cli, fix_items, wait_items, actions)
        current = greptile.get("status") == "ok" and not greptile.get("stale")
        return greptile, "greptile" if current else ""
    if mode == GREPTILE_OPTIONAL:
        bot = parse_greptile(github)
        if bot["status"] == "ok" and not bot["stale"]:
            return bot, "greptile"
    claude = claude_review_status(github)
    if claude == "ok":
        return {"status": "off"}, "claude"
    if mode == GREPTILE_OPTIONAL and _no_claude_workflow(github):
        # No Claude Code review workflow in this repository: Greptile decides.
        greptile = _evaluate_greptile_required(github, greptile_cli, fix_items, wait_items, actions)
        current = greptile.get("status") == "ok" and not greptile.get("stale")
        return greptile, "greptile" if current else ""
    if _claude_review_running(github):
        wait_items.append("Ревью Claude Code ещё выполняется.")
    elif claude == "stale":
        wait_items.append("Ревью Claude Code относится к старому коммиту: нужен повторный ревью.")
        actions.append("rerun_claude_review")
    else:
        wait_items.append("Нет ревью Claude Code (и текущего ревью Greptile).")
    return {"status": "off"}, ""


def _evaluate_greptile_score(greptile: Dict[str, Any], blockers: List[str]) -> None:
    if greptile.get("status") != "ok" or greptile.get("stale"):
        return
    if greptile["confidence"] < 4:
        blockers.append(f"Greptile: уверенность {greptile['confidence']}/5, нужно 5/5.")
    elif greptile["confidence"] == 4 and not greptile["explanation"]:
        blockers.append("Greptile: 4/5 без объяснения, что он не может проверить.")


def _evaluate_sonar(sonar: Dict[str, Any], blockers: List[str], fix_items: List[Dict[str, Any]],
                    wait_items: List[str]) -> str:
    """Add Sonar findings. Return a blocker text when a human must decide."""
    status = sonar.get("status")
    if status == "not_configured":
        return "SonarCloud не настроен: ключ проекта не найден."
    if status == "error":
        return f"SonarCloud недоступен: {sonar.get('error', '')}."
    if status == "no_analysis":
        wait_items.append("SonarCloud ещё не проанализировал этот PR.")
        return ""
    if status != "ok":
        return ""
    if sonar.get("gate") == "NONE":
        wait_items.append("Quality gate SonarCloud ещё не рассчитан.")
    elif sonar.get("gate") != "OK":
        blockers.append(f"Quality gate SonarCloud: {sonar.get('gate')}.")
    if sonar.get("issues_total", 0) > 0:
        for issue in sonar.get("issues", []):
            fix_items.append({"kind": "sonar", **issue})
    coverage = sonar.get("new_coverage")
    if coverage is None:
        if sonar.get("new_lines_to_cover") not in (None, 0.0):
            wait_items.append("SonarCloud ещё не посчитал покрытие нового кода.")
    elif coverage < REQUIRED_COVERAGE:
        blockers.append(f"Покрытие нового кода {coverage:g}%, нужно 100%.")
    return ""


def _evaluate_greptile_required(github: Dict[str, Any], greptile_cli: Optional[Dict[str, Any]],
                                fix_items: List[Dict[str, Any]], wait_items: List[str],
                                actions: List[str]) -> Dict[str, Any]:
    """Greptile as the deciding review: the bot summary first, then the CLI review of the head commit."""
    greptile = parse_greptile(github)
    if greptile["status"] == "ok" and not greptile["stale"]:
        return greptile
    cli = greptile_cli or {"status": "missing"}
    if cli.get("status") == "ok":
        return _greptile_from_cli(cli, fix_items)
    if cli.get("status") == "running":
        wait_items.append("Ревью Greptile CLI ещё выполняется.")
    elif greptile["status"] == "ok":
        wait_items.append("Оценка Greptile относится к старому коммиту: нужен повторный ревью.")
        actions.append("run_greptile_review")
    else:
        wait_items.append("Нет ревью Greptile для текущего коммита.")
        actions.append("run_greptile_review")
    return greptile


def _greptile_from_cli(cli: Dict[str, Any], fix_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    explanation = ""
    if cli["confidence"] == 4:
        match = _UNVERIFIABLE_RE.search(cli.get("reasoning") or "")
        explanation = match.group(0).strip() if match else ""
    for comment in cli.get("comments") or []:
        fix_items.append({
            "kind": "greptile",
            "path": comment.get("path") or comment.get("file") or "",
            "line": comment.get("line") or comment.get("startLine"),
            "body": (comment.get("body") or comment.get("message") or comment.get("text") or "")[:500],
        })
    return {"status": "ok", "source": "cli", "confidence": cli["confidence"],
            "explanation": explanation, "stale": False}


def _result(verdict, blockers, fix_items, wait_items, greptile, sonar, conflict) -> Dict[str, Any]:
    return {
        "verdict": verdict,
        "actions": [],
        "conflict": conflict,
        "blockers": blockers,
        "fix_items": fix_items,
        "wait_items": wait_items,
        "greptile": greptile,
        "sonar": sonar,
    }


def greptile_mode(project_dir: str) -> str:
    """Read pr_loop.greptile from the project config; unknown values mean required."""
    from core.config_loader import load_config

    config = load_config(os.path.join(project_dir, ".claude", "alfred-dev.local.md"))
    raw = (config.get("pr_loop") or {}).get("greptile", GREPTILE_OPTIONAL)
    # YAML 1.1 reads a bare off/no as false and on/yes as true.
    if isinstance(raw, bool):
        return GREPTILE_REQUIRED if raw else GREPTILE_OFF
    mode = str(raw).strip().lower()
    mode = _MODE_ALIASES.get(mode, mode)
    return mode if mode in GREPTILE_MODES else GREPTILE_REQUIRED


def pr_status(project_dir: str, pr: Optional[str] = None,
              run: Optional[Runner] = None, fetch: Optional[Fetcher] = None,
              greptile_run: Optional[GreptileRunner] = None) -> Dict[str, Any]:
    """Collect everything and evaluate. Errors become a needs_user verdict."""
    try:
        github = collect_github(project_dir, pr, run=run)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"verdict": VERDICT_NEEDS_USER, "blockers": [f"GitHub CLI: {exc}"],
                "fix_items": [], "wait_items": [], "conflict": False}
    sonar = collect_sonar(find_sonar_project_key(project_dir), int(github["number"]), fetch=fetch)
    mode = greptile_mode(project_dir)
    greptile_cli = None
    if needs_greptile_cli(github, mode):
        greptile_cli = collect_greptile_cli(project_dir, github.get("headRefOid", ""), run=greptile_run)
    result = evaluate(github, sonar, greptile_cli, greptile_mode=mode)
    result.update({
        "pr": github.get("number"),
        "url": github.get("url", ""),
        "repository": github.get("repository", ""),
        "head": github.get("headRefName", ""),
        "base": github.get("baseRefName", ""),
        "max_rounds": MAX_ROUNDS,
    })
    return result


_VERDICT_LABELS = {
    VERDICT_MERGE: "можно мержить",
    VERDICT_FIX: "нужно исправить замечания",
    VERDICT_CONFLICT: "нужно разрешить конфликт с базовой веткой",
    VERDICT_WAIT: "нужно подождать проверки и ревью",
    VERDICT_NEEDS_USER: "нужно решение человека",
    VERDICT_DONE: "PR уже закрыт или смержен",
}


def render_pr_status(result: Dict[str, Any]) -> str:
    """Render the status as Russian Markdown for the session."""
    verdict = result.get("verdict", VERDICT_NEEDS_USER)
    lines = [
        f"`PR_STATUS_{verdict.upper()}`",
        "",
        f"## PR #{result.get('pr', '?')}: {_VERDICT_LABELS.get(verdict, verdict)}",
        "",
    ]
    lines += _render_summary(result)
    if result.get("blockers"):
        lines += ["", "### Блокеры", ""] + [f"- {item}" for item in result["blockers"]]
    if result.get("fix_items"):
        lines += ["", "### Что исправить", ""] + [_render_fix_item(item) for item in result["fix_items"]]
    if result.get("wait_items"):
        lines += ["", "### Ожидание", ""] + [f"- {item}" for item in result["wait_items"]]
    lines += _render_actions(result.get("actions") or [])
    return "\n".join(lines) + "\n"


def _render_summary(result: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if result.get("url"):
        lines.append(f"- Ссылка: {result['url']}")
    if result.get("head"):
        lines.append(f"- Ветка: `{result['head']}` → `{result.get('base', '')}`")
    lines += _render_greptile(result.get("greptile") or {})
    if result.get("ai_review") == "claude":
        lines.append("- ИИ-ревью: Claude Code")
    sonar = result.get("sonar") or {}
    if sonar.get("status") == "ok":
        coverage = sonar.get("new_coverage")
        coverage_text = "нет новых строк" if coverage is None else f"{coverage:g}%"
        lines.append(
            f"- SonarCloud: gate `{sonar.get('gate')}`, issues {sonar.get('issues_total', 0)}, "
            f"покрытие нового кода {coverage_text}"
        )
    return lines


def _render_greptile(greptile: Dict[str, Any]) -> List[str]:
    if greptile.get("status") == "off":
        return ["- Greptile: не требуется"]
    if greptile.get("status") != "ok":
        return []
    stale = " (устарела)" if greptile.get("stale") else ""
    source = " (Greptile CLI)" if greptile.get("source") == "cli" else ""
    lines = [f"- Greptile: {greptile['confidence']}/5{source}{stale}"]
    if greptile.get("explanation"):
        lines.append(f"  - Что не может проверить: {greptile['explanation']}")
    return lines


def _render_fix_item(item: Dict[str, Any]) -> str:
    where = f"{item.get('path')}:{item.get('line')}" if item.get("path") else "общее"
    kind = item["kind"]
    if kind == "thread":
        return f"- Тред `{item.get('id')}` ({item.get('author')}, {where}): {item.get('body')}"
    if kind == "check":
        return f"- Check `{item.get('name')}`: {item.get('outcome')} {item.get('url', '')}".rstrip()
    if kind == "greptile":
        return f"- Greptile ({where}): {item.get('body')}"
    return f"- Sonar `{item.get('rule')}` {item.get('component')}:{item.get('line')}: {item.get('message')}"


def _render_actions(actions: List[str]) -> List[str]:
    lines: List[str] = []
    if "rerun_claude_review" in actions:
        lines += ["", "### Действие", "",
                  "- Повтори ревью: закрой и снова открой PR (`gh pr close <номер>`, затем `gh pr reopen <номер>`)."]
    if "run_greptile_review" in actions:
        lines += ["", "### Действие", "",
                  "- Запусти ревью Greptile CLI для текущего коммита ветки: `greptile review --agent --json`."]
    return lines
