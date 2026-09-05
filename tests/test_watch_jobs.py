import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from watch_jobs import job_key, parse_greenhouse, parse_micro1, run, update_source

SOURCE = {"id": "test", "kind": "greenhouse", "board": "test", "employer": "Test",
          "url": "https://example.org/jobs", "complete_snapshot": True}


def row(identifier="1", title="Software Engineer"):
    return {"id": "greenhouse:test:" + identifier, "source_id": "test", "title": title,
            "url": "https://boards.greenhouse.io/test/jobs/" + identifier,
            "listing_state": "listed", "description": "Remote", "posted_at": None}


class WatchTests(unittest.TestCase):
    def test_duplicate_tracking_urls_and_distinct_roles(self):
        a = "https://boards.greenhouse.io/test/jobs/12?source=linkedin"
        b = "https://job-boards.greenhouse.io/test/jobs/12?gh_src=mail"
        self.assertEqual(job_key(a), job_key(b))
        self.assertNotEqual(job_key(a), job_key(b.replace("/12?", "/13?")))

    def test_repeat_snapshot_preserves_first_seen_and_does_not_realert(self):
        state = {}
        self.assertEqual(len(update_source(state, SOURCE, [row(), row()], "t1")), 1)
        self.assertEqual(update_source(state, SOURCE, [row()], "t2"), [])
        self.assertEqual(state["jobs"][row()["id"]]["first_seen_at"], "t1")
        self.assertIsNone(state["jobs"][row()["id"]]["posted_at"])

    def test_failure_preserves_jobs_and_last_success(self):
        state = {}
        update_source(state, SOURCE, [row()], "t1")
        update_source(state, SOURCE, [], "t2", error="HTTP 403")
        self.assertEqual(state["jobs"][row()["id"]]["listing_state"], "listed")
        self.assertEqual(state["sources"]["test"]["last_success_at"], "t1")
        self.assertEqual(state["sources"]["test"]["status"], "error")

    def test_partial_index_absence_is_not_closure(self):
        state = {}
        partial = {**SOURCE, "complete_snapshot": False}
        update_source(state, partial, [row()], "t1")
        update_source(state, partial, [row("2")], "t2")
        self.assertEqual(state["jobs"][row()["id"]]["listing_state"], "listed")

    def test_missing_from_complete_feed_and_reappearance(self):
        state = {}
        update_source(state, SOURCE, [row()], "t1")
        update_source(state, SOURCE, [row("2")], "t2")
        self.assertEqual(state["jobs"][row()["id"]]["listing_state"], "not_listed")
        events = update_source(state, SOURCE, [row(), row("2")], "t3")
        self.assertEqual(events[0]["event"], "reappeared")
        self.assertEqual(state["jobs"][row()["id"]]["first_seen_at"], "t1")

    def test_empty_or_malformed_feed_is_not_success(self):
        for payload in ('{"jobs": []}', '{"error": "blocked"}', '<html>challenge</html>'):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                parse_greenhouse(payload, SOURCE)

    def test_greenhouse_updated_at_is_not_posting_time(self):
        payload = json.dumps({"jobs": [{"id": 1, "title": "AI Tutor", "updated_at": "t2",
            "absolute_url": "https://boards.greenhouse.io/test/jobs/1",
            "content": "&lt;p&gt;Remote coding&lt;/p&gt;"}]})
        result = parse_greenhouse(payload, SOURCE)[0]
        self.assertIsNone(result["posted_at"])
        self.assertNotIn("description", result)
        self.assertEqual(len(result["description_hash"]), 64)

    def test_micro1_card_retains_pay_without_inventing_exact_timestamp(self):
        payload = '<a href="https://jobs.micro1.ai/post/abc-123?src=test">Sep 3, 2026<h2>Software Engineer</h2>Required skills Python Pay: $10-20/h</a>'
        result = parse_micro1(payload, {"id": "micro", "employer": "micro1"})[0]
        self.assertEqual(result["title"], "Software Engineer")
        self.assertEqual(result["posted_label"], "Sep 3, 2026")
        self.assertEqual(result["compensation_text"], "$10-20/h")
        self.assertIsNone(result["posted_at"])
        self.assertEqual(result["listing_state"], "index_only")

    def test_new_run_recovers_persisted_state_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder) / "sources.json", Path(folder) / "jobs.json"
            config.write_text(json.dumps({"sources": [SOURCE]}))
            run(config, state, fetcher=lambda source: [row()], now="t1")
            def failed(source):
                raise HTTPError(source["url"], 403, "Forbidden", None, None)
            summary = run(config, state, fetcher=failed, now="t2")
            self.assertEqual(summary["sources_failed"], 1)
            self.assertEqual(summary["jobs_retained"], 1)
            self.assertEqual(json.loads(state.read_text())["jobs"][row()["id"]]["first_seen_at"], "t1")

    def test_browser_source_is_not_counted_as_successful_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder) / "sources.json", Path(folder) / "jobs.json"
            config.write_text(json.dumps({"sources": [{**SOURCE, "execution": "browser_required", "reason": "Rendered page needed"}]}))
            summary = run(config, state, fetcher=lambda source: self.fail("Must not fetch"), now="t1")
            self.assertEqual(summary["sources_checked"], 0)
            self.assertEqual(summary["sources_require_browser"], 1)
            self.assertEqual(json.loads(state.read_text())["sources"]["test"]["status"], "browser_required")


if __name__ == "__main__":
    unittest.main()
