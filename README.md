# Public vacancy watch

A small, credential-free monitor for public AI and engineering vacancies. It
retains first-seen times, posting labels, listing changes and source failures.
The original `scrape_jobs.py` remains a separate legacy scraper. Run
`watch_jobs.py` manually; it does not invoke Selenium or sign into sites.

## Run

```sh
python3 -m unittest discover -s tests -v
python3 watch_jobs.py
```

Python 3.10+ and the standard library are sufficient. `sources.json` currently
configures the public SpaceXAI/xAI and Outlier/Remotasks Greenhouse boards.
micro1 is explicitly marked `browser_required`: its rendered opportunities page
works in a browser, but the live HTTP response contains no job cards. The worker
does not claim that source as successfully polled. A separate connected-assistant
check covers it. These sources supplement broader searches; they are not
exhaustive coverage of all platforms. Add sources only after verifying their
public interface and parser behavior.

## GitHub Actions disabled; manual output

GitHub Actions automation was disabled at the owner's request on September 11,
2026. The former workflow is archived at
`.github/disabled-workflows/watch-jobs.yml`, outside GitHub's executable workflow
directory. There are no active workflow files. Do not restore or re-enable
Actions without the owner's explicit request.

The manual command above writes public listing observations and source coverage
to `data/public_jobs.json` locally; it does not automatically commit or publish
the output. State is loaded again on the next manual run, with jobs keyed by
employer/ATS posting ID. Unchanged observations do not generate another new-job
event. Read `last_run` and `sources` before trusting the feed: a failed request
preserves previous jobs and records an error, rather than reporting no vacancies.

## Interpreting observations

- `first_seen_at` means first observed by this monitor, not newly posted.
- `posted_at` stays null unless supplied. Greenhouse `updated_at` is stored
  separately. Date-only micro1 labels are retained as labels without invented
  publication times.
- `listed` means present in the public Greenhouse board.
- `index_only` means present in micro1's public index. Confirm the individual
  page before applying; a search result or index card may be stale.
- `not_listed` means absent from a later complete board snapshot, not a personal
  rejection. Absence from the partial micro1 index never closes a record.
- Keyword coverage is broad with no pay floor. Location and legal eligibility
  remain unverified for application review. On-site or region-limited roles may
  appear; discovery is not an assertion of eligibility.

## Application boundary

This public repository stores public vacancies only. Keep resumes, email,
phone, immigration answers, existing applications, receipts and account access
in a separate private tracker. A connected assistant can consume new public
observations, deduplicate against that private tracker, and complete supported
initial application forms when the required facts and permissions are available.
This script does not sign in, submit applications, take assessments or email
employers. It needs no model API key or third-party account credentials.

Public feed reference: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html).
