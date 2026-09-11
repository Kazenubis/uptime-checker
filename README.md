# Website Uptime Checker

Pings a watchlist of URLs and tracks each one's up/down state across
checks — but only logs the moments a URL's status actually *changes*, so
a site that's been down for hours produces one alert, not one line per
check.

Real output from a 2-cycle run (one URL stays up, one goes down between
cycles):

```
--- Cycle 1 ---
https://kazenubis-portfolio.example.com: up
https://flaky-supplier-api.example.com: up
OK: https://kazenubis-portfolio.example.com is up (first check)
OK: https://flaky-supplier-api.example.com is up (first check)

--- Cycle 2 (supplier API goes down) ---
https://kazenubis-portfolio.example.com: up
https://flaky-supplier-api.example.com: down
ALERT: https://flaky-supplier-api.example.com is DOWN - Connection refused

--- uptime_log.txt ---
2026-09-11T04:29:52+00:00 https://kazenubis-portfolio.example.com unknown -> up
2026-09-11T04:29:52+00:00 https://flaky-supplier-api.example.com unknown -> up
2026-09-11T04:29:52+00:00 https://flaky-supplier-api.example.com up -> down (Connection refused)
```

## Features

- Checks any list of URLs on an interval; a non-2xx/3xx response or a
  connection failure both count as "down" — a network error never
  crashes the tool, it's just another kind of down result
- Logs only status *transitions*, not every check — persisted state
  (`uptime_state.json`) means a URL that's still down on check #50 of the
  day doesn't write 50 more log lines
- A simple notification hook (defaults to printing; swap in a real
  webhook/email call by passing a different `sink`) fires on both going
  down and recovering
- Watchlist is a small JSON file — easy to point at your own portfolio
  site, API, or anything else worth watching

## Tech Stack

Python 3 · `requests`

## Getting Started

```bash
git clone https://github.com/Kazenubis/uptime-checker.git
cd uptime-checker
pip install -r requirements.txt
python3 uptime_checker.py --watchlist watchlist.json --count 1
```

Run it continuously (5-minute interval, 12 checks = 1 hour):

```bash
python3 uptime_checker.py --watchlist watchlist.json --interval 300 --count 12
```

Run the tests:

```bash
python3 -m unittest test_uptime_checker.py -v
```

## What I Learned

The "only log transitions" behavior is the part that actually needed a
test, not just the obvious "is it up or down" check. It's easy to write
a version that logs every single check and call it done, but that's not
actually useful output — a downtime log should read like an incident
timeline, not a heartbeat. `test_a_url_down_across_multiple_cycles_logs_only_once`
runs the same downed URL through 3 check cycles and confirms exactly one
log line comes out, which is the behavior that actually makes the log
worth reading later.
