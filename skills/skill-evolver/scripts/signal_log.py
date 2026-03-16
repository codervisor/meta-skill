#!/usr/bin/env python3
"""
skill-evolver: signal_log.py
Records and queries skill execution signals.

Usage:
  python signal_log.py record <skill-name> <type> <json-data>
  python signal_log.py query <skill-name> [--type failure] [--since 2024-01-01] [--limit 20]
  python signal_log.py summarize <skill-name>
  python signal_log.py summarize-all

Signal types: failure, fix, health_check, user_feedback, execution, observation
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

SIGNAL_DIR = Path.home() / ".skill-signals"


def ensure_dir(skill_name: str) -> Path:
    d = SIGNAL_DIR / skill_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(skill_name: str, signal_type: str, data: dict):
    d = ensure_dir(skill_name)
    log_file = d / "signals.jsonl"

    entry = {
        "type": signal_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **data
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def read_signals(skill_name: str, signal_type=None, since=None, limit=None):
    log_file = SIGNAL_DIR / skill_name / "signals.jsonl"
    if not log_file.exists():
        return []

    signals = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if signal_type and entry.get("type") != signal_type:
                continue
            if since and entry.get("timestamp", "") < since:
                continue

            signals.append(entry)

    if limit:
        signals = signals[-limit:]

    return signals


def summarize(skill_name: str) -> dict:
    signals = read_signals(skill_name)
    if not signals:
        return {"skill": skill_name, "total": 0, "status": "no data"}

    type_counts = Counter(s["type"] for s in signals)

    failures = [s for s in signals if s["type"] == "failure"]
    root_causes = Counter(s.get("root_cause", "unknown") for s in failures)

    recent = [s for s in signals if s.get("timestamp", "") >
              (datetime.utcnow() - timedelta(days=7)).isoformat()]
    recent_failures = sum(1 for s in recent if s["type"] == "failure")

    fixes = [s for s in signals if s["type"] == "fix"]
    verified_fixes = sum(1 for f in fixes if f.get("verified", False))

    observations = [s for s in signals if s["type"] == "observation"]
    obs_with_errors = sum(1 for o in observations if o.get("errors_found"))
    obs_with_discrepancies = sum(1 for o in observations if o.get("discrepancies"))

    return {
        "skill": skill_name,
        "total_signals": len(signals),
        "by_type": dict(type_counts),
        "failures": {
            "total": len(failures),
            "root_causes": dict(root_causes),
            "recent_7d": recent_failures,
        },
        "fixes": {
            "total": len(fixes),
            "verified": verified_fixes,
        },
        "observations": {
            "total": len(observations),
            "with_errors": obs_with_errors,
            "with_discrepancies": obs_with_discrepancies,
        },
        "health": _health_rating(len(failures), recent_failures, verified_fixes,
                                 len(fixes), obs_with_discrepancies),
        "recommendation": _recommendation(root_causes, recent_failures, obs_with_discrepancies),
    }


def _health_rating(total_failures, recent_failures, verified_fixes, total_fixes,
                    obs_discrepancies=0):
    if obs_discrepancies >= 2:
        return "unreliable-reporting"
    if total_failures == 0 and obs_discrepancies == 0:
        return "healthy"
    if recent_failures >= 3:
        return "degraded"
    if total_fixes > 0 and verified_fixes / total_fixes < 0.5:
        return "unstable"
    if total_failures > 5 and total_fixes == 0:
        return "needs-attention"
    return "fair"


def _recommendation(root_causes, recent_failures, obs_discrepancies=0):
    recs = []
    if obs_discrepancies >= 2:
        recs.append(
            f"Observation discrepancies ({obs_discrepancies}): "
            "agent self-reports don't match execution artifacts. "
            "Run observe_execution.py to cross-reference."
        )
    if root_causes:
        top_cause, count = root_causes.most_common(1)[0]
        if count >= 3:
            recs.append(f"Recurring issue: {top_cause} ({count} times). Consider structural fix.")
    if recent_failures >= 3:
        recs.append("Recent spike in failures. Run diagnosis.")
    return recs if recs else None


def summarize_all():
    if not SIGNAL_DIR.exists():
        return []

    results = []
    for skill_dir in sorted(SIGNAL_DIR.iterdir()):
        if skill_dir.is_dir():
            results.append(summarize(skill_dir.name))
    return results


def main():
    parser = argparse.ArgumentParser(description="Skill signal logger")
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record")
    rec.add_argument("skill_name")
    rec.add_argument("signal_type", choices=["failure", "fix", "health_check", "user_feedback", "execution", "observation"])
    rec.add_argument("data", help="JSON string")

    q = sub.add_parser("query")
    q.add_argument("skill_name")
    q.add_argument("--type", dest="signal_type")
    q.add_argument("--since")
    q.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("summarize")
    s.add_argument("skill_name")

    sub.add_parser("summarize-all")

    args = parser.parse_args()

    if args.command == "record":
        data = json.loads(args.data)
        entry = record(args.skill_name, args.signal_type, data)
        print(json.dumps(entry, indent=2))

    elif args.command == "query":
        signals = read_signals(args.skill_name, args.signal_type, args.since, args.limit)
        print(json.dumps(signals, indent=2))

    elif args.command == "summarize":
        print(json.dumps(summarize(args.skill_name), indent=2))

    elif args.command == "summarize-all":
        print(json.dumps(summarize_all(), indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
