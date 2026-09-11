"""
Website Uptime Checker — pings a watchlist of URLs, tracks each one's
last-known status, and logs only the *transitions* (up->down, down->up)
rather than every single check — so a URL that's been down for an hour
produces one log line, not 360 identical ones.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

DEFAULT_TIMEOUT = 5
DEFAULT_STATE_PATH = "uptime_state.json"
DEFAULT_LOG_PATH = "uptime_log.txt"


def load_watchlist(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["urls"]


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def check_url(url, timeout=DEFAULT_TIMEOUT):
    """Checks one URL. Returns a result dict; never raises — a
    connection failure or timeout is itself a 'down' result, not an
    exception the caller has to handle."""
    checked_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    try:
        response = requests.get(url, timeout=timeout)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        status = "up" if response.status_code < 400 else "down"
        return {
            "url": url,
            "status": status,
            "status_code": response.status_code,
            "response_time_ms": elapsed_ms,
            "checked_at": checked_at,
            "error": None,
        }
    except requests.RequestException as e:
        return {
            "url": url,
            "status": "down",
            "status_code": None,
            "response_time_ms": None,
            "checked_at": checked_at,
            "error": str(e),
        }


def run_check_cycle(urls, state, timeout=DEFAULT_TIMEOUT):
    """Checks every URL once. Returns (results, transitions, new_state).
    A transition is only recorded when a URL's status differs from the
    last cycle's recorded status for it (or it's being seen for the first
    time and comes back down)."""
    results = []
    transitions = []
    new_state = dict(state)

    for url in urls:
        result = check_url(url, timeout=timeout)
        results.append(result)

        previous_status = state.get(url)
        if result["status"] != previous_status:
            transitions.append({
                "url": url,
                "from_status": previous_status or "unknown",
                "to_status": result["status"],
                "checked_at": result["checked_at"],
                "error": result["error"],
            })
        new_state[url] = result["status"]

    return results, transitions, new_state


def format_transition_line(transition):
    detail = f" ({transition['error']})" if transition["error"] else ""
    return (
        f"{transition['checked_at']} {transition['url']} "
        f"{transition['from_status']} -> {transition['to_status']}{detail}"
    )


def log_transitions(log_path, transitions):
    if not transitions:
        return
    with open(log_path, "a", encoding="utf-8") as f:
        for transition in transitions:
            f.write(format_transition_line(transition) + "\n")


def notify(transition, sink=print):
    """Notification hook. Defaults to printing to stdout; pass a
    different `sink` (e.g. a list's .append) to capture calls in tests or
    wire up a real notification channel."""
    if transition["to_status"] == "down":
        sink(f"ALERT: {transition['url']} is DOWN{' - ' + transition['error'] if transition['error'] else ''}")
    elif transition.get("from_status") == "unknown":
        sink(f"OK: {transition['url']} is up (first check)")
    else:
        sink(f"RECOVERED: {transition['url']} is back up")


def main():
    parser = argparse.ArgumentParser(description="Website Uptime Checker")
    parser.add_argument("--watchlist", default="watchlist.json")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--log", default=DEFAULT_LOG_PATH)
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks")
    parser.add_argument("--count", type=int, default=1, help="Number of check cycles to run")
    args = parser.parse_args()

    urls = load_watchlist(args.watchlist)
    state = load_state(args.state)

    for cycle in range(args.count):
        results, transitions, state = run_check_cycle(urls, state)
        for result in results:
            print(f"{result['checked_at']} {result['url']}: {result['status']} "
                  f"({result['status_code'] or 'n/a'}, {result['response_time_ms'] or '-'}ms)")
        for transition in transitions:
            notify(transition)
        log_transitions(args.log, transitions)
        save_state(args.state, state)

        if cycle < args.count - 1:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
