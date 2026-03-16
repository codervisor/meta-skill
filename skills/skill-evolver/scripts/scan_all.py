#!/usr/bin/env python3
"""
skill-evolver: scan_all.py
Run health checks on all installed skills and produce a system-wide report.

Usage:
  python scan_all.py [--json] [--scope claude-global,claude-project,...]
"""

import sys
import json
from pathlib import Path
from health_check import run_health_check


def _discover_scopes():
    """Discover skill directories across all standard locations."""
    home = Path.home()
    cwd = Path.cwd()
    scopes = {}

    scopes["claude-global"] = home / ".claude" / "skills"
    scopes["claude-project"] = cwd / ".claude" / "skills"
    scopes["agent-global"] = home / ".agent" / "skills"
    scopes["agent-project"] = cwd / ".agent" / "skills"
    scopes["agents-project"] = cwd / ".agents" / "skills"
    scopes["runtime-public"] = Path("/mnt/skills/public")
    scopes["runtime-user"] = Path("/mnt/skills/user")
    scopes["runtime-private"] = Path("/mnt/skills/private")
    scopes["runtime-examples"] = Path("/mnt/skills/examples")

    return {k: v for k, v in scopes.items() if v.exists()}

SKILL_SCOPES = _discover_scopes()


def find_all_skills(scopes=None):
    """Find all skill directories across scopes."""
    if scopes is None:
        scopes = SKILL_SCOPES.keys()

    skills = []
    for scope_name in scopes:
        scope_path = SKILL_SCOPES.get(scope_name)
        if not scope_path or not scope_path.exists():
            continue
        for item in sorted(scope_path.iterdir()):
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append({
                    "scope": scope_name,
                    "path": str(item),
                    "name": item.name,
                })
    return skills


def scan_all(scopes=None):
    skills = find_all_skills(scopes)
    reports = []

    for skill in skills:
        report = run_health_check(skill["path"])
        reports.append({
            "scope": skill["scope"],
            "name": report.skill_name,
            "path": skill["path"],
            "summary": report.summary(),
            "checks": [{"name": c.name, "status": c.status, "message": c.message}
                       for c in report.checks],
        })

    return reports


def print_text_report(reports):
    print("=" * 60)
    print("SKILL ECOSYSTEM HEALTH REPORT")
    print("=" * 60)
    print()

    total_pass = total_warn = total_fail = 0

    for r in reports:
        s = r["summary"]
        total_pass += s["PASS"]
        total_warn += s["WARN"]
        total_fail += s["FAIL"]

        status_icon = "✓" if s["FAIL"] == 0 and s["WARN"] == 0 else ("⚠" if s["FAIL"] == 0 else "✗")
        print(f"  {status_icon} [{r['scope']}] {r['name']}: {s['PASS']}P / {s['WARN']}W / {s['FAIL']}F")

        issues = [c for c in r["checks"] if c["status"] != "PASS"]
        for issue in issues:
            print(f"      [{issue['status']}] {issue['name']}: {issue['message']}")

    print()
    print(f"Total: {len(reports)} skills, {total_pass} passed, {total_warn} warnings, {total_fail} failures")

    print()
    print("─" * 40)
    print("Trigger Overlap Analysis")
    print("─" * 40)
    overlap_issues = []
    for r in reports:
        for c in r["checks"]:
            if c["name"] == "trigger/overlap" and c["status"] == "WARN":
                overlap_issues.append(f"  {r['name']}: {c['message']}")

    if overlap_issues:
        for o in overlap_issues:
            print(o)
    else:
        print("  No significant overlaps detected.")


if __name__ == "__main__":
    use_json = "--json" in sys.argv

    scopes = None
    for arg in sys.argv[1:]:
        if arg.startswith("--scope"):
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                scopes = sys.argv[idx + 1].split(",")

    reports = scan_all(scopes)

    if use_json:
        print(json.dumps(reports, indent=2))
    else:
        print_text_report(reports)
