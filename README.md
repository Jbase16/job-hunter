# Public vacancy watch

A small, credential-free monitor for public AI and engineering vacancies. It
retains first-seen times, posting labels, listing changes and source failures.
The original `scrape_jobs.py` remains a separate legacy scraper; the scheduled
workflow runs `watch_jobs.py` and does not invoke Selenium or sign into sites.

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

## Schedule and durable output

The GitHub Actions workflow checks at minutes 7, 22, 37 and 52 each hour. Pushes
that change the monitor on `main` also run it. Enable Actions for this repository
if it is disabled. The first successful hosted run is the deployment check.

The workflow commits titles, locations, URLs, timestamps and description hashes
to `data/public_jobs.json`; it does not republish full job descriptions. State is
loaded again on the next run, with jobs keyed by employer/ATS posting ID.
Unchanged observations do not generate another new-job event. Read `last_run`
and `sources` before trusting the feed: a failed request preserves previous jobs
and records an error, rather than reporting no vacancies. A failed run still
commits its coverage evidence when the runner has repository write permission.

GitHub schedules can be delayed or dropped under load; this is periodic polling,
not a guaranteed real-time feed. Scheduled workflows run on the default branch
and can be disabled after 60 days without repository activity. See
[GitHub schedule behavior](https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#schedule).

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
