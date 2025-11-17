#!/usr/bin/env python3

import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List

import requests
from bs4 import BeautifulSoup


# ==========================
# CONFIGURATION
# ==========================

# Default search configuration. You can change these or pass values via CLI.
DEFAULT_SEARCH_TERMS = ["security engineer", "junior security", "automation engineer", "technical support", "mac support"]
DEFAULT_LOCATION = "sacramento, CA"
DEFAULT_MAX_PAGES = 10  # Number of result pages per search to fetch (Indeed paginates)

OUTPUT_FILE = "jobs.json"


# ==========================
# DATA MODEL
# ==========================

@dataclass
class JobPosting:
    source: str
    title: str
    company: str
    location: str
    url: str
    summary: str
    posted_raw: str
    scraped_at: str
    search_term: str


# ==========================
# SCRAPER: INDEED
# ==========================

def build_indeed_url(query: str, location: str, start: int = 0) -> str:
    """
    Build a basic Indeed search URL.

    Note:
    - This uses the public search page, not any private API.
    - Markup can and does change; selectors below may need updates over time.
    """
    base = "https://www.indeed.com/jobs"
    params = {
        "q": query,
        "l": location,
        "start": str(start),
    }
    # We manually build the query string to keep dependencies minimal.
    query_string = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{base}?{query_string}"


def fetch_page(url: str) -> str:
    """
    Fetch a single page of HTML from a public job listing URL.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15"
        )
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_indeed_jobs(html: str, search_term: str) -> List[JobPosting]:
    """
    Parse Indeed job cards from a search result page.

    IMPORTANT:
    - Indeed frequently changes its CSS class names and structure.
    - If this stops working, inspect the HTML in your browser (View Source or DevTools)
      and adjust selectors accordingly.
    """
    soup = BeautifulSoup(html, "html.parser")

    # This selector may need updates; it's a generic "job card" style container.
    job_cards = soup.select("div.job_seen_beacon") or soup.select("div.jobsearch-SerpJobCard")

    postings: List[JobPosting] = []
    scraped_at = datetime.utcnow().isoformat() + "Z"

    for card in job_cards:
        # Title and URL
        title_element = card.select_one("h2 a") or card.select_one("h2.jobTitle a")
        if not title_element:
            continue

        title = title_element.get("aria-label") or title_element.get_text(strip=True)
        href = title_element.get("href") or ""
        if href.startswith("/"):
            url = "https://www.indeed.com" + href
        else:
            url = href

        # Company
        company_element = (
            card.select_one("span.companyName") or
            card.select_one("span.company") or
            card.select_one("div.company")
        )
        company = company_element.get_text(strip=True) if company_element else ""

        # Location
        location_element = (
            card.select_one("div.companyLocation") or
            card.select_one("div.location") or
            card.select_one("span.location")
        )
        location = location_element.get_text(strip=True) if location_element else ""

        # Summary / snippet
        summary_element = (
            card.select_one("div.job-snippet") or
            card.select_one("div.summary")
        )
        summary = " ".join(
            summary_element.get_text(separator=" ", strip=True).split()
        ) if summary_element else ""

        # Posted time ("Just posted", "3 days ago", etc.)
        posted_element = (
            card.select_one("span.date") or
            card.select_one("span.datePosted")
        )
        posted_raw = posted_element.get_text(strip=True) if posted_element else ""

        posting = JobPosting(
            source="indeed",
            title=title,
            company=company,
            location=location,
            url=url,
            summary=summary,
            posted_raw=posted_raw,
            scraped_at=scraped_at,
            search_term=search_term,
        )
        postings.append(posting)

    return postings


def search_indeed_for_term(term: str, location: str, max_pages: int) -> List[JobPosting]:
    """
    Search Indeed for a given term and location, fetching up to max_pages of results.
    """
    all_postings: List[JobPosting] = []

    for page in range(max_pages):
        start = page * 10  # Indeed uses increments of 10 for pagination
        url = build_indeed_url(term, location, start=start)
        print(f"[Indeed] Fetching page {page + 1}/{max_pages} for '{term}' @ '{location}'")
        print(f"         URL: {url}")

        try:
            html = fetch_page(url)
        except requests.HTTPError as e:
            print(f"HTTP error fetching {url}: {e}")
            break
        except requests.RequestException as e:
            print(f"Request error fetching {url}: {e}")
            break

        page_postings = parse_indeed_jobs(html, term)
        print(f"         Found {len(page_postings)} job(s) on this page.")
        if not page_postings:
            # No more jobs or structure changed
            break

        all_postings.extend(page_postings)

        # Be polite: pause between requests
        time.sleep(2)

    return all_postings


# ==========================
# DEDUPLICATION / OUTPUT
# ==========================

def deduplicate_jobs(jobs: List[JobPosting]) -> List[JobPosting]:
    """
    Deduplicate by (source, url) combination.
    """
    seen = set()
    unique_jobs: List[JobPosting] = []
    for job in jobs:
        key = (job.source, job.url)
        if key in seen:
            continue
        seen.add(key)
        unique_jobs.append(job)
    return unique_jobs


def save_jobs_to_file(jobs: List[JobPosting], filename: str) -> None:
    data = [asdict(job) for job in jobs]
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved {len(jobs)} job(s) to {filename}")


# ==========================
# CLI ENTRY POINT
# ==========================

def main() -> None:
    """
    Usage:
        python scrape_jobs.py
        python scrape_jobs.py "security engineer" "remote" 3

    If arguments are provided:
        arg1 = search term
        arg2 = location
        arg3 = max pages (optional)
    If no arguments, uses DEFAULT_SEARCH_TERMS and DEFAULT_LOCATION.
    """
    if len(sys.argv) >= 2:
        # Single custom search term
        term = sys.argv[1]
        location = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_LOCATION
        try:
            max_pages = int(sys.argv[3]) if len(sys.argv) >= 4 else DEFAULT_MAX_PAGES
        except ValueError:
            max_pages = DEFAULT_MAX_PAGES

        search_terms = [term]
        search_location = location
    else:
        search_terms = DEFAULT_SEARCH_TERMS
        search_location = DEFAULT_LOCATION
        max_pages = DEFAULT_MAX_PAGES

    print("=== Job Scraper: Indeed (MVP) ===")
    print(f"Search terms: {search_terms}")
    print(f"Location: {search_location}")
    print(f"Max pages per term: {max_pages}\n")

    all_jobs: List[JobPosting] = []
    for term in search_terms:
        jobs = search_indeed_for_term(term, search_location, max_pages)
        all_jobs.extend(jobs)

    unique_jobs = deduplicate_jobs(all_jobs)
    save_jobs_to_file(unique_jobs, OUTPUT_FILE)


if __name__ == "__main__":
    main()
