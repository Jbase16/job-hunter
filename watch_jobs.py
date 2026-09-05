#!/usr/bin/env python3
"""Read public vacancy feeds and retain changes. No accounts or applications."""
import argparse
import hashlib
import html
import json
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

KEYWORDS = re.compile(
    r"engineer|developer|software|coding|programming|\bai\b|\bml\b|machine learning|"
    r"evaluat|annotat|\bqa\b|quality|test|debug|security|cyber|data|scient|"
    r"biolog|biomed|medical|chemistr|physics|math|research|generalist|technical|"
    r"infrastructure|devops|systems|frontend|front.end|backend|full.stack|\brl\b",
    re.I,
)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected a public HTTPS job URL")
    return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def job_key(url):
    parts = urlsplit(canonical_url(url))
    match = re.fullmatch(r"/([^/]+)/jobs/(\d+)", parts.path)
    if parts.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io",
                           "job-boards.eu.greenhouse.io"} and match:
        return f"greenhouse:{match[1].lower()}:{match[2]}"
    if parts.hostname == "jobs.micro1.ai" and re.fullmatch(r"/post/[a-f0-9-]+", parts.path):
        return "micro1:" + parts.path.rsplit("/", 1)[-1]
    return canonical_url(url)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plaintext(value):
    parser = TextParser()
    parser.feed(html.unescape(value))
    return " ".join(" ".join(parser.parts).split())


class MicroCards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.current = None
        self.heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href", "")
        if tag == "a" and href.startswith("https://jobs.micro1.ai/post/"):
            self.current = {"url": canonical_url(href), "text": [], "heading": []}
        if self.current and tag == "h2":
            self.heading = True

    def handle_endtag(self, tag):
        if tag == "h2":
            self.heading = False
        if tag == "a" and self.current:
            self.cards.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.current["text"].append(data)
            if self.heading:
                self.current["heading"].append(data)


def parse_greenhouse(payload, source):
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("Greenhouse response did not contain a jobs list")
    rows = []
    for item in data["jobs"]:
        if not all(item.get(k) is not None for k in ("id", "title", "absolute_url")):
            raise ValueError("Incomplete Greenhouse job record")
        description = plaintext(item.get("content") or "")
        rows.append({
            "id": f"greenhouse:{source['board']}:{item['id']}",
            "employer": source["employer"], "title": item["title"],
            "url": canonical_url(item["absolute_url"]),
            "location": (item.get("location") or {}).get("name"),
            "description_hash": hashlib.sha256(description.encode()).hexdigest(),
            "remote_hint": "remote" in ((item.get("location") or {}).get("name") or "").lower(),
            "assessment_mentioned": bool(re.search(r"assessment|interview", description, re.I)),
            "posted_at": item.get("first_published"),
            "source_updated_at": item.get("updated_at"),
            "posted_label": None, "compensation_text": None,
            "source_id": source["id"], "listing_state": "listed",
        })
    # An unexpectedly empty response needs review; it must not erase history.
    if not rows:
        raise ValueError("Empty Greenhouse snapshot; retained previous jobs")
    return rows


def parse_micro1(payload, source):
    parser = MicroCards()
    parser.feed(payload)
    rows = []
    for card in parser.cards:
        title = " ".join(" ".join(card["heading"]).split())
        text = " ".join(" ".join(card["text"]).split())
        if not title:
            continue
        posted = re.search(r"\b[A-Z][a-z]{2} \d{1,2}, \d{4}\b", text)
        pay = re.search(r"Pay:\s*(.+?)(?=$)", text)
        rows.append({
            "id": job_key(card["url"]), "employer": source["employer"],
            "title": title, "url": card["url"], "location": None,
            "description": text, "posted_at": None,
            "posted_label": posted[0] if posted else None,
            "source_updated_at": None,
            "compensation_text": pay[1] if pay else None,
            "source_id": source["id"], "listing_state": "index_only",
        })
    if not rows:
        raise ValueError("No readable micro1 cards; page may require JavaScript or have changed")
    return rows


def fetch_source(source):
    request = Request(source["url"], headers={
        "User-Agent": "job-hunter-public-feed-monitor/1.0",
        "Accept": "application/json, text/html;q=0.9",
    })
    # A failed or restricted source is recorded, never retried through evasion.
    with urlopen(request, timeout=25) as response:
        payload = response.read(12_000_001)
    if len(payload) > 12_000_000:
        raise ValueError("Source exceeded the response size limit")
    content = payload.decode("utf-8")
    if source["kind"] == "greenhouse":
        return parse_greenhouse(content, source)
    if source["kind"] == "micro1_index":
        return parse_micro1(content, source)
    raise ValueError("Unsupported source kind")


def update_source(state, source, rows, now, error=None):
    jobs = state.setdefault("jobs", {})
    sources = state.setdefault("sources", {})
    previous = sources.get(source["id"], {})
    coverage = {"url": source["url"], "checked_at": now,
                "complete_snapshot": source.get("complete_snapshot", False),
                "last_success_at": previous.get("last_success_at"),
                "status": "error" if error else "ok", "error": error,
                "records_received": None if error else len(rows)}
    sources[source["id"]] = coverage
    if error:
        return []
    coverage["last_success_at"] = now
    events = []
    seen = set()
    for row in rows:
        key = row["id"]
        seen.add(key)
        if not KEYWORDS.search(row["title"]):
            continue
        old = jobs.get(key)
        comparable = {k: v for k, v in row.items() if k != "source_updated_at"}
        digest = hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()
        event = None
        if old is None:
            event = "first_seen"
        elif old["listing_state"] == "not_listed":
            event = "reappeared"
        elif old.get("content_hash") != digest:
            event = "changed"
        jobs[key] = {**row, "content_hash": digest,
                     "first_seen_at": old["first_seen_at"] if old else now,
                     "last_seen_at": now,
                     "last_changed_at": now if event else old["last_changed_at"],
                     "eligibility": "unverified", "application_state": "not_tracked_publicly"}
        if event:
            events.append({"id": key, "event": event, "at": now,
                           "title": row["title"], "url": row["url"]})
    if source.get("complete_snapshot"):
        for key, row in jobs.items():
            if row["source_id"] == source["id"] and key not in seen and row["listing_state"] != "not_listed":
                row["listing_state"] = "not_listed"
                row["last_changed_at"] = now
                events.append({"id": key, "event": "not_listed", "at": now,
                               "title": row["title"], "url": row["url"]})
    return events


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def run(config_path, state_path, fetcher=fetch_source, now=None):
    now = now or utcnow()
    config = json.loads(Path(config_path).read_text())
    state_file = Path(state_path)
    state = json.loads(state_file.read_text()) if state_file.exists() else {"schema_version": 1}
    if state.get("schema_version") != 1:
        raise ValueError("Unknown state schema; refusing to overwrite it")
    ids = [s["id"] for s in config["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Source IDs must be unique")
    events, failures, skipped = [], 0, 0
    for source in config["sources"]:
        if source.get("execution") == "browser_required":
            skipped += 1
            state.setdefault("sources", {})[source["id"]] = {
                "url": source["url"], "status": "browser_required",
                "reason": source["reason"], "checked_at": now,
                "last_success_at": state.get("sources", {}).get(source["id"], {}).get("last_success_at"),
                "complete_snapshot": False,
            }
            continue
        try:
            rows = fetcher(source)
        except Exception as exc:
            failures += 1
            events.extend(update_source(state, source, [], now,
                error=f"{type(exc).__name__}: {str(exc)[:250]}"))
        else:
            events.extend(update_source(state, source, rows, now))
    summary = {"at": now, "sources_configured": len(ids), "sources_checked": len(ids) - skipped,
               "sources_require_browser": skipped, "sources_failed": failures,
               "change_count": len(events), "jobs_retained": len(state.get("jobs", {}))}
    state["last_run"] = summary
    state["runs"] = (state.get("runs", []) + [summary])[-96:]
    state["events"] = (state.get("events", []) + events)[-3000:]
    save_json(state_path, state)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="sources.json")
    parser.add_argument("--state", default="data/public_jobs.json")
    args = parser.parse_args()
    summary = run(args.config, args.state)
    print(json.dumps(summary))
    return 2 if summary["sources_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
