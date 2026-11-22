#!/usr/bin/env python3
"""Tests for the PR loop status and gate decision."""

import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.pr_status import (  # noqa: E402
    VERDICT_CONFLICT,
    VERDICT_DONE,
    VERDICT_FIX,
    VERDICT_MERGE,
    VERDICT_NEEDS_USER,
    VERDICT_WAIT,
    collect_greptile_cli,
    collect_sonar,
    evaluate,
    find_sonar_project_key,
    parse_greptile,
    pr_status,
    render_pr_status,
)

HEAD = "abc123"


def _greptile(confidence, body_extra="", commit=HEAD, at="2026-11-22T12:00:00Z"):
    return {
        "author": {"login": "greptile-apps"},
        "body": f"<h3>Greptile Summary</h3>\n\nConfidence Score: {confidence}/5\n\n{body_extra}",
        "submittedAt": at,
        "commit": {"oid": commit},
    }


def _github(**overrides):
    data = {
        "number": 7,
        "url": "https://github.com/o/r/pull/7",
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "headRefName": "feat/x",
        "headRefOid": HEAD,
        "baseRefName": "main",
        "reviewDecision": "",
        "statusCheckRollup": [
            {"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"context": "SonarCloud Code Analysis", "state": "SUCCESS"},
        ],
        "comments": [],
        "reviews": [_greptile(5)],
        "commits": [{"oid": HEAD, "committedDate": "2026-11-22T11:00:00Z"}],
        "reviewThreads": [{"id": "T1", "isResolved": True, "comments": {"nodes": []}}],
    }
    data.update(overrides)
    return data


GREEN_SONAR = {"status": "ok", "gate": "OK", "issues_total": 0, "issues": [],
               "new_coverage": 100.0, "new_lines_to_cover": 12.0}


class TestEvaluate(unittest.TestCase):
    def test_all_green_merges(self):
        self.assertEqual(evaluate(_github(), GREEN_SONAR)["verdict"], VERDICT_MERGE)

    def test_unresolved_thread_needs_fix(self):
        thread = {
            "id": "T2", "isResolved": False, "path": "src/a.py", "line": 3,
            "comments": {"nodes": [{"author": {"login": "alice"}, "body": "Rename this.", "url": "u"}]},
        }
        result = evaluate(_github(reviewThreads=[thread]), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_FIX)
        self.assertEqual(result["fix_items"][0]["id"], "T2")
        self.assertEqual(result["fix_items"][0]["author"], "alice")

    def test_human_changes_requested_needs_fix(self):
        result = evaluate(_github(reviewDecision="CHANGES_REQUESTED"), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_FIX)

    def test_failed_check_needs_fix(self):
        checks = [{"name": "build", "status": "COMPLETED", "conclusion": "FAILURE", "detailsUrl": "d"}]
        result = evaluate(_github(statusCheckRollup=checks), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_FIX)
        self.assertEqual(result["fix_items"][0]["name"], "build")

    def test_running_check_waits(self):
        checks = [{"name": "build", "status": "IN_PROGRESS", "conclusion": ""},
                  {"context": "ci/legacy", "state": "PENDING"}]
        result = evaluate(_github(statusCheckRollup=checks), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_WAIT)
        self.assertEqual(len(result["wait_items"]), 2)

    def test_conflict_wins(self):
        thread = {"id": "T3", "isResolved": False, "comments": {"nodes": [{}]}}
        result = evaluate(_github(mergeable="CONFLICTING", reviewThreads=[thread]), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_CONFLICT)

    def test_greptile_three_needs_fix(self):
        result = evaluate(_github(reviews=[_greptile(3)]), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_FIX)

    def test_greptile_four_without_reason_needs_fix(self):
        result = evaluate(_github(reviews=[_greptile(4, "Looks good overall.")]), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_FIX)

    def test_greptile_four_with_reason_merges(self):
        body = "It cannot verify the runtime behavior of the PDF renderer without running it."
        result = evaluate(_github(reviews=[_greptile(4, body)]), GREEN_SONAR)
        self.assertEqual(result["verdict"], VERDICT_MERGE)
        self.assertIn("cannot verify", result["greptile"]["explanation"])

    def test_greptile_missing_or_stale_waits_and_asks_for_review(self):
        missing = evaluate(_github(reviews=[]), GREEN_SONAR)
        self.assertEqual(missing["verdict"], VERDICT_WAIT)
        self.assertIn("run_greptile_review", missing["actions"])
        stale = evaluate(_github(reviews=[_greptile(5, commit="old999")]), GREEN_SONAR)
        self.assertEqual(stale["verdict"], VERDICT_WAIT)
        self.assertIn("run_greptile_review", stale["actions"])

    def test_greptile_cli_review_replaces_missing_bot(self):
        cli = {"status": "ok", "confidence": 5, "reasoning": "", "comments": []}
        result = evaluate(_github(reviews=[]), GREEN_SONAR, cli)
        self.assertEqual(result["verdict"], VERDICT_MERGE)
        self.assertEqual(result["greptile"]["source"], "cli")

    def test_greptile_cli_four_needs_reason(self):
        no_reason = {"status": "ok", "confidence": 4, "reasoning": "Small change.", "comments": []}
        self.assertEqual(evaluate(_github(reviews=[]), GREEN_SONAR, no_reason)["verdict"], VERDICT_FIX)
        reason = dict(no_reason, reasoning="The review could not verify the SMTP delivery without a mail server.")
        self.assertEqual(evaluate(_github(reviews=[]), GREEN_SONAR, reason)["verdict"], VERDICT_MERGE)

    def test_greptile_cli_comments_become_fix_items(self):
        cli = {"status": "ok", "confidence": 5, "reasoning": "",
               "comments": [{"path": "src/A.java", "line": 9, "body": "Null check missing."}]}
        result = evaluate(_github(reviews=[]), GREEN_SONAR, cli)
        self.assertEqual(result["verdict"], VERDICT_FIX)
        self.assertEqual(result["fix_items"][0]["kind"], "greptile")
        self.assertIn("Null check", render_pr_status(result))

    def test_greptile_cli_running_waits(self):
        result = evaluate(_github(reviews=[]), GREEN_SONAR, {"status": "running"})
        self.assertEqual(result["verdict"], VERDICT_WAIT)
        self.assertNotIn("run_greptile_review", result["actions"])

    def test_greptile_comment_older_than_head_is_stale(self):
        comment = {"author": {"login": "greptile-apps[bot]"}, "body": "Confidence: 5/5",
                   "updatedAt": "2026-11-22T10:00:00Z"}
        greptile = parse_greptile(_github(reviews=[], comments=[comment]))
        self.assertTrue(greptile["stale"])

    def test_sonar_issues_and_coverage_need_fix(self):
        sonar = dict(GREEN_SONAR, issues_total=1, new_coverage=97.5,
                     issues=[{"key": "k", "rule": "java:S1", "message": "m", "component": "c", "line": 4}])
        result = evaluate(_github(), sonar)
        self.assertEqual(result["verdict"], VERDICT_FIX)
        self.assertTrue(any(item["kind"] == "sonar" for item in result["fix_items"]))
        self.assertTrue(any("97.5%" in item for item in result["blockers"]))

    def test_sonar_gate_failed_needs_fix(self):
        self.assertEqual(evaluate(_github(), dict(GREEN_SONAR, gate="ERROR"))["verdict"], VERDICT_FIX)

    def test_sonar_without_new_lines_is_fine(self):
        sonar = dict(GREEN_SONAR, new_coverage=None, new_lines_to_cover=0.0)
        self.assertEqual(evaluate(_github(), sonar)["verdict"], VERDICT_MERGE)

    def test_sonar_not_analyzed_waits(self):
        self.assertEqual(evaluate(_github(), {"status": "no_analysis"})["verdict"], VERDICT_WAIT)

    def test_sonar_not_configured_needs_user(self):
        self.assertEqual(evaluate(_github(), {"status": "not_configured"})["verdict"], VERDICT_NEEDS_USER)

    def test_draft_needs_user(self):
        self.assertEqual(evaluate(_github(isDraft=True), GREEN_SONAR)["verdict"], VERDICT_NEEDS_USER)

    def test_merged_is_done(self):
        self.assertEqual(evaluate(_github(state="MERGED"), GREEN_SONAR)["verdict"], VERDICT_DONE)


class TestGreptileCli(unittest.TestCase):
    def test_reads_status_and_review(self):
        def run(args):
            if args[:2] == ["review", "status"]:
                return 0, json.dumps({"commit": HEAD, "status": "completed", "runId": "r1", "confidence": 4})
            return 0, json.dumps({"confidenceReasoning": "Cannot verify the UI.", "comments": [{"path": "a", "line": 1, "body": "b"}]})

        cli = collect_greptile_cli(".", HEAD, run=run)
        self.assertEqual(cli["confidence"], 4)
        self.assertEqual(cli["reasoning"], "Cannot verify the UI.")
        self.assertEqual(len(cli["comments"]), 1)

    def test_no_review_and_running(self):
        none = lambda args: (0, json.dumps({"commit": HEAD, "status": None, "runId": None, "confidence": None}))
        self.assertEqual(collect_greptile_cli(".", HEAD, run=none)["status"], "missing")
        running = lambda args: (3, json.dumps({"commit": HEAD, "status": "running", "runId": "r", "confidence": None}))
        self.assertEqual(collect_greptile_cli(".", HEAD, run=running)["status"], "running")


class TestSonar(unittest.TestCase):
    def test_finds_key_in_properties_pom_and_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_sonar_project_key(tmp), "")
            with open(os.path.join(tmp, "pom.xml"), "w", encoding="utf-8") as fh:
                fh.write("<properties><sonar.projectKey>grigoriev_im</sonar.projectKey></properties>")
            self.assertEqual(find_sonar_project_key(tmp), "grigoriev_im")
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".github", "workflows"))
            with open(os.path.join(tmp, ".github", "workflows", "ci.yml"), "w", encoding="utf-8") as fh:
                fh.write("run: mvn sonar:sonar -Dsonar.projectKey=o_r\n")
            self.assertEqual(find_sonar_project_key(tmp), "o_r")
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "sonar-project.properties"), "w", encoding="utf-8") as fh:
                fh.write("sonar.organization=o\nsonar.projectKey=o_web\n")
            self.assertEqual(find_sonar_project_key(tmp), "o_web")

    def test_collect_sonar_reads_gate_issues_and_coverage(self):
        def fetch(url):
            if "qualitygates" in url:
                return {"projectStatus": {"status": "OK"}}
            if "issues/search" in url:
                return {"total": 0, "issues": []}
            return {"component": {"measures": [
                {"metric": "new_coverage", "periods": [{"index": 1, "value": "100.0"}]},
                {"metric": "new_lines_to_cover", "periods": [{"index": 1, "value": "8"}]},
            ]}}

        sonar = collect_sonar("o_r", 7, fetch=fetch)
        self.assertEqual(sonar["gate"], "OK")
        self.assertEqual(sonar["new_coverage"], 100.0)
        self.assertEqual(sonar["new_lines_to_cover"], 8.0)

    def test_collect_sonar_maps_404_to_no_analysis(self):
        def fetch(url):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)

        self.assertEqual(collect_sonar("o_r", 7, fetch=fetch)["status"], "no_analysis")
        self.assertEqual(collect_sonar("", 7, fetch=fetch)["status"], "not_configured")


class TestPrStatus(unittest.TestCase):
    def test_pr_status_runs_gh_and_renders(self):
        github = _github()
        threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        calls = []

        def run(args):
            calls.append(args)
            if args[:2] == ["pr", "view"]:
                return json.dumps({k: v for k, v in github.items() if k != "reviewThreads"})
            if args[:2] == ["repo", "view"]:
                return json.dumps({"owner": {"login": "o"}, "name": "r"})
            return json.dumps(threads)

        def fetch(url):
            if "qualitygates" in url:
                return {"projectStatus": {"status": "OK"}}
            if "issues/search" in url:
                return {"total": 0, "issues": []}
            return {"component": {"measures": [{"metric": "new_coverage", "period": {"value": "100"}}]}}

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "sonar-project.properties"), "w", encoding="utf-8") as fh:
                fh.write("sonar.projectKey=o_r\n")
            result = pr_status(tmp, "7", run=run, fetch=fetch)

        self.assertEqual(result["verdict"], VERDICT_MERGE)
        self.assertEqual(result["repository"], "o/r")
        self.assertEqual(calls[0][:3], ["pr", "view", "7"])
        self.assertFalse(any(call[:2] == ["repo", "view"] for call in calls))
        text = render_pr_status(result)
        self.assertIn("`PR_STATUS_MERGE`", text)
        self.assertIn("Greptile: 5/5", text)

    def test_pr_status_reports_gh_failure(self):
        def run(args):
            raise RuntimeError("no pull requests found")

        result = pr_status(".", None, run=run)
        self.assertEqual(result["verdict"], VERDICT_NEEDS_USER)
        self.assertIn("no pull requests found", result["blockers"][0])


if __name__ == "__main__":
    unittest.main()
