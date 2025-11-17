#!/usr/bin/env python3

import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


# ==========================
# CONFIGURATION
# ==========================

# Default search configuration. You can change these or pass values via CLI.
DEFAULT_SEARCH_TERMS = ["entry level security engineer", "junior security", "junior automation engineer", "technical support","mac support"]
DEFAULT_LOCATION = "Sacramento, CA"
DEFAULT_MAX_PAGES = 5  # Number of result pages per search per source

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
# HTTP HELPERS
# ==========================

def fetch_page(url: str) -> str:
    """
    Fetch a single page of HTML from a public URL.
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


# ==========================
# SCRAPER: INDEED VIA SELENIUM
# ==========================

def build_indeed_url(query: str, location: str, start: int = 0) -> str:
    """
    Build a basic Indeed search URL.
    """
    base = "https://www.indeed.com/jobs"
    params = {
        "q": query,
        "l": location,
        "start": str(start),
    }
    query_string = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{base}?{query_string}"


def parse_indeed_jobs(html: str, search_term: str) -> List[JobPosting]:
    """
    Parse Indeed job cards from a search result page.

    NOTE:
    - Indeed frequently changes its HTML.
    - If this breaks, inspect the HTML and update selectors.
    """
    soup = BeautifulSoup(html, "html.parser")

    job_cards = soup.select("div.job_seen_beacon") or soup.select("div.jobsearch-SerpJobCard")

    postings: List[JobPosting] = []
    scraped_at = datetime.utcnow().isoformat() + "Z"

    for card in job_cards:
        title_element = card.select_one("h2 a") or card.select_one("h2.jobTitle a")
        if not title_element:
            continue

        title = title_element.get("aria-label") or title_element.get_text(strip=True)
        href = title_element.get("href") or ""
        if href.startswith("/"):
            url = "https://www.indeed.com" + href
        else:
            url = href

        company_element = (
            card.select_one("span.companyName") or
            card.select_one("span.company") or
            card.select_one("div.company")
        )
        company = company_element.get_text(strip=True) if company_element else ""

        location_element = (
            card.select_one("div.companyLocation") or
            card.select_one("div.location") or
            card.select_one("span.location")
        )
        location = location_element.get_text(strip=True) if location_element else ""

        summary_element = (
            card.select_one("div.job-snippet") or
            card.select_one("div.summary")
        )
        summary = " ".join(
            summary_element.get_text(separator=" ", strip=True).split()
        ) if summary_element else ""

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
    Search Indeed for a given term and location using a real Chrome browser
    via Selenium, to avoid basic bot blocking.
    """
    all_postings: List[JobPosting] = []

    options = Options()
    # Full visible browser (Option C): no headless flag
    driver = webdriver.Chrome(options=options)

    try:
        for page in range(max_pages):
            start = page * 10
            url = build_indeed_url(term, location, start=start)
            print(f"[Indeed] (Selenium) Fetching page {page + 1}/{max_pages} for '{term}' @ '{location}'")
            print(f"         URL: {url}")

            driver.get(url)

            # Let the page fully render (JS, lazy load, etc.)
            time.sleep(5)

            html = driver.page_source
            page_postings = parse_indeed_jobs(html, term)
            print(f"         Found {len(page_postings)} job(s) on this page.")
            if not page_postings:
                break

            all_postings.extend(page_postings)

            # Small pause between pages
            time.sleep(3)
    finally:
        driver.quit()

    return all_postings


# ==========================
# SCRAPER: GOOGLE SEARCH (SITE-FILTERED TO LINKEDIN JOBS)
# ==========================

def build_google_jobs_url(query: str, location: str, start: int = 0) -> str:
    """
    Build a Google search URL aimed at LinkedIn job listings.

    We use a site: filter so Google gives us primarily LinkedIn job URLs.
    """
    base = "https://www.google.com/search"
    # Example: site:linkedin.com/jobs/ "security engineer" remote
    q = f'site:linkedin.com/jobs/ "{query}" {location}'
    params = {
        "q": q,
        "start": str(start),
    }
    query_string = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{base}?{query_string}"


def parse_google_jobs(html: str, search_term: str) -> List[JobPosting]:
    """
    Parse Google SERP results for LinkedIn job URLs.

    We don't try to extract full job data here; we just collect URLs and basic titles.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = soup.select("div.g")

    postings: List[JobPosting] = []
    scraped_at = datetime.utcnow().isoformat() + "Z"

    for r in results:
        link = r.select_one("a")
        title_el = r.select_one("h3")
        snippet_el = r.select_one("div.VwiC3b") or r.select_one("span.aCOpRe")

        if not link or not title_el:
            continue

        url = link.get("href", "")
        if "linkedin.com/jobs" not in url:
            continue

        title = title_el.get_text(strip=True)
        summary = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        posting = JobPosting(
            source="google_linkedin",
            title=title,
            company="",
            location="",
            url=url,
            summary=summary,
            posted_raw="",
            scraped_at=scraped_at,
            search_term=search_term,
        )
        postings.append(posting)

    return postings


def search_google_jobs_for_term(term: str, location: str, max_pages: int) -> List[JobPosting]:
    """
    Use Google search as a LinkedIn job URL finder via site: filter.
    """
    all_postings: List[JobPosting] = []

    for page in range(max_pages):
        start = page * 10
        url = build_google_jobs_url(term, location, start=start)
        print(f"[Google→LinkedIn] Fetching page {page + 1}/{max_pages} for '{term}' @ '{location}'")
        print(f"                 URL: {url}")

        try:
            html = fetch_page(url)
        except requests.HTTPError as e:
            print(f"    HTTP error fetching {url}: {e}")
            break
        except requests.RequestException as e:
            print(f"    Request error fetching {url}: {e}")
            break

        page_postings = parse_google_jobs(html, term)
        print(f"                 Found {len(page_postings)} result(s) on this page.")
        if not page_postings:
            break

        all_postings.extend(page_postings)
        time.sleep(2)

    return all_postings


# ==========================
# SCRAPER: LINKEDIN PUBLIC JOB SEARCH
# ==========================

def build_linkedin_url(query: str, location: str, page: int = 0) -> str:
    """
    Build a LinkedIn public job search URL.
    """
    base = "https://www.linkedin.com/jobs/search"
    params = {
        "keywords": query,
        "location": location,
        "position": "1",
        "pageNum": str(page),
    }
    query_string = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{base}?{query_string}"


def parse_linkedin_jobs(html: str, search_term: str) -> List[JobPosting]:
    """
    Parse LinkedIn public job search results.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.base-card")

    postings: List[JobPosting] = []
    scraped_at = datetime.utcnow().isoformat() + "Z"

    for card in cards:
        link_el = card.select_one("a.base-card__full-link")
        if not link_el:
            continue

        url = link_el.get("href", "").split("?")[0]

        title_el = card.select_one("h3.base-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        summary_el = card.select_one("p.base-search-card__snippet")
        posted_el = card.select_one("time")

        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        location = location_el.get_text(strip=True) if location_el else ""
        summary = summary_el.get_text(strip=True) if summary_el else ""
        posted_raw = posted_el.get_text(strip=True) if posted_el else ""

        posting = JobPosting(
            source="linkedin",
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


def search_linkedin_for_term(term: str, location: str, max_pages: int) -> List[JobPosting]:
    """
    Search LinkedIn public job pages for a given term and location.
    """
    all_postings: List[JobPosting] = []

    for page in range(max_pages):
        url = build_linkedin_url(term, location, page=page)
        print(f"[LinkedIn] Fetching page {page + 1}/{max_pages} for '{term}' @ '{location}'")
        print(f"           URL: {url}")

        try:
            html = fetch_page(url)
        except requests.HTTPError as e:
            print(f"    HTTP error fetching {url}: {e}")
            break
        except requests.RequestException as e:
            print(f"    Request error fetching {url}: {e}")
            break

        page_postings = parse_linkedin_jobs(html, term)
        print(f"           Found {len(page_postings)} job(s) on this page.")
        if not page_postings:
            break

        all_postings.extend(page_postings)
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
    """
    if len(sys.argv) >= 2:
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

    print("=== Job Scraper: Indeed(Selenium) + Google(site:linkedin) + LinkedIn ===")
    print(f"Search terms: {search_terms}")
    print(f"Location: {search_location}")
    print(f"Max pages per term per source: {max_pages}\n")

    all_jobs: List[JobPosting] = []

    for term in search_terms:
        indeed_jobs = search_indeed_for_term(term, search_location, max_pages)
        all_jobs.extend(indeed_jobs)

        google_jobs = search_google_jobs_for_term(term, search_location, max_pages)
        all_jobs.extend(google_jobs)

        linkedin_jobs = search_linkedin_for_term(term, search_location, max_pages)
        all_jobs.extend(linkedin_jobs)

    unique_jobs = deduplicate_jobs(all_jobs)
    save_jobs_to_file(unique_jobs, OUTPUT_FILE)


if __name__ == "__main__":
    main()
