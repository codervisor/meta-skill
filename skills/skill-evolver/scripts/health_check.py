#!/usr/bin/env python3
"""
skill-evolver: health_check.py
Static analysis of skill quality. Scans a skill directory and reports issues.

Usage:
  python health_check.py /path/to/skill-dir [--json]
"""

import sys
import os
import re
import json
import glob
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class Check:
    name: str
    status: str  # PASS, WARN, FAIL
    message: str
    severity: int = 0  # 0=info, 1=warn, 2=error

@dataclass
class HealthReport:
    skill_name: str
    skill_path: str
    checks: list = field(default_factory=list)

    def add(self, name, status, message, severity=0):
        self.checks.append(Check(name, status, message, severity))

    def summary(self):
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    def to_text(self):
        lines = [
            f"Skill Health Report: {self.skill_name}",
            "━" * 40,
        ]
        for c in self.checks:
            icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[c.status]
            lines.append(f"  [{icon} {c.status}] {c.name}: {c.message}")

        s = self.summary()
        lines.append("")
        lines.append(f"Summary: {s['PASS']} passed, {s['WARN']} warnings, {s['FAIL']} failures")

        fails = [c for c in self.checks if c.status == "FAIL"]
        warns = [c for c in self.checks if c.status == "WARN"]
        if fails or warns:
            lines.append("")
            lines.append("Recommendations:")
            for i, c in enumerate(fails + warns, 1):
                lines.append(f"  {i}. [{c.status}] {c.name} — {c.message}")

        return "\n".join(lines)


def parse_frontmatter(content: str) -> Optional[dict]:
    """Extract YAML frontmatter from SKILL.md."""
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).strip().split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            fm[k.strip()] = v.strip()
    return fm


def check_structure(skill_dir: Path, report: HealthReport):
    """Check basic skill structure."""
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        report.add("structure/skill-md", "FAIL", "SKILL.md not found", 2)
        return

    report.add("structure/skill-md", "PASS", "SKILL.md exists")

    content = skill_md.read_text(encoding='utf-8', errors='replace')
    fm = parse_frontmatter(content)

    if not fm:
        report.add("structure/frontmatter", "FAIL", "No YAML frontmatter found", 2)
        return

    if 'name' not in fm:
        report.add("structure/name", "FAIL", "Missing 'name' in frontmatter", 2)
    else:
        report.add("structure/name", "PASS", f"name: {fm['name']}")

    if 'description' not in fm:
        report.add("structure/description", "FAIL", "Missing 'description' in frontmatter", 2)
    else:
        desc = fm['description']
        word_count = len(desc.split())
        if word_count < 20:
            report.add("structure/description-length", "WARN",
                       f"Description too short ({word_count} words). Aim for 50+ for reliable triggering.", 1)
        elif word_count < 50:
            report.add("structure/description-length", "WARN",
                       f"Description could be longer ({word_count} words). Consider adding more trigger phrases.", 1)
        else:
            report.add("structure/description-length", "PASS", f"Description length OK ({word_count} words)")


def check_references(skill_dir: Path, content: str, report: HealthReport):
    """Check that file references in SKILL.md actually exist."""
    refs = re.findall(r'(?:scripts|references|assets)/[\w\-\.]+\.\w+', content)

    if not refs:
        report.add("references/files", "PASS", "No file references to check")
        return

    missing = []
    for ref in set(refs):
        if not (skill_dir / ref).exists():
            missing.append(ref)

    if missing:
        report.add("references/files", "FAIL",
                   f"Referenced files not found: {', '.join(missing)}", 2)
    else:
        report.add("references/files", "PASS", f"All {len(set(refs))} referenced files exist")


def check_instruction_quality(content: str, report: HealthReport):
    """Analyze instruction quality for common anti-patterns."""
    lines = content.split('\n')
    body_start = content.find('---', 4)
    if body_start > 0:
        body = content[body_start + 3:]
    else:
        body = content

    forceful = re.findall(r'\b(MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT)\b', body)
    if len(forceful) > 10:
        report.add("quality/forceful-language", "WARN",
                   f"Heavy use of forceful language ({len(forceful)} instances). "
                   "Consider explaining the 'why' instead of commanding.", 1)
    else:
        report.add("quality/forceful-language", "PASS",
                   f"Forceful language within limits ({len(forceful)})")

    hardcoded = re.findall(r'(?:/home/\w+|/Users/\w+|C:\\\\)', body)
    if hardcoded:
        report.add("quality/hardcoded-paths", "WARN",
                   f"Hardcoded paths found: {hardcoded[:3]}. Use relative paths or variables.", 1)
    else:
        report.add("quality/hardcoded-paths", "PASS", "No hardcoded user paths")

    error_terms = re.findall(r'\b(error|fail|exception|fallback|retry|if.*wrong|if.*broken)\b',
                             body, re.IGNORECASE)
    if len(error_terms) < 2:
        report.add("quality/error-handling", "WARN",
                   "Minimal error handling guidance. Consider adding fallback instructions.", 1)
    else:
        report.add("quality/error-handling", "PASS", "Error handling instructions present")

    line_count = len(lines)
    if line_count > 500:
        report.add("quality/length", "WARN",
                   f"SKILL.md is {line_count} lines. Consider moving detail to references/.", 1)
    else:
        report.add("quality/length", "PASS", f"Length OK ({line_count} lines)")

    always_patterns = re.findall(r'(?:always|must)\s+(\w+)', body, re.IGNORECASE)
    never_patterns = re.findall(r'(?:never|must not|don\'t)\s+(\w+)', body, re.IGNORECASE)
    overlap = set(always_patterns) & set(never_patterns)
    if overlap:
        report.add("quality/contradictions", "WARN",
                   f"Possible contradictions around: {', '.join(overlap)}", 1)
    else:
        report.add("quality/contradictions", "PASS", "No obvious contradictions detected")


def check_scripts(skill_dir: Path, report: HealthReport):
    """Check script health."""
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        report.add("scripts/exists", "PASS", "No scripts directory (not required)")
        return

    scripts = list(scripts_dir.glob("*.py")) + list(scripts_dir.glob("*.sh"))
    if not scripts:
        report.add("scripts/empty", "WARN", "Scripts directory exists but is empty", 1)
        return

    for script in scripts:
        content = script.read_text(encoding='utf-8', errors='replace')

        if not content.startswith('#!'):
            report.add(f"scripts/{script.name}/shebang", "WARN",
                      f"{script.name} missing shebang line", 1)

        if 'except:' in content and 'except Exception' not in content:
            report.add(f"scripts/{script.name}/bare-except", "WARN",
                      f"{script.name} has bare except clause", 1)

    report.add("scripts/count", "PASS", f"{len(scripts)} scripts found")


def check_trigger_overlap(skill_dir: Path, fm: dict, report: HealthReport):
    """Check if this skill's description overlaps with other installed skills."""
    if not fm or 'description' not in fm:
        return

    this_desc = fm['description'].lower()
    this_name = fm.get('name', '')

    home = Path.home()
    cwd = Path.cwd()
    scan_dirs = [
        home / ".claude" / "skills",
        cwd / ".claude" / "skills",
        home / ".agent" / "skills",
        cwd / ".agent" / "skills",
        cwd / ".agents" / "skills",
        Path("/mnt/skills/public"),
        Path("/mnt/skills/user"),
        Path("/mnt/skills/private"),
    ]
    overlaps = []
    for scope_path in scan_dirs:
        if not scope_path.exists():
            continue
        for other_dir in scope_path.iterdir():
            if not other_dir.is_dir() or other_dir.name == this_name:
                continue
            other_md = other_dir / "SKILL.md"
            if not other_md.exists():
                continue
            other_content = other_md.read_text(encoding='utf-8', errors='replace')
            other_fm = parse_frontmatter(other_content)
            if not other_fm or 'description' not in other_fm:
                continue

            other_desc = other_fm['description'].lower()
            this_words = set(this_desc.split()) - {'the', 'a', 'an', 'is', 'to', 'for', 'or', 'and', 'use', 'this', 'when'}
            other_words = set(other_desc.split()) - {'the', 'a', 'an', 'is', 'to', 'for', 'or', 'and', 'use', 'this', 'when'}
            shared = this_words & other_words
            ratio = len(shared) / max(len(this_words), 1)

            if ratio > 0.3:
                overlaps.append((other_fm.get('name', other_dir.name), ratio, shared))

    if overlaps:
        top = sorted(overlaps, key=lambda x: -x[1])[:3]
        details = "; ".join(f"{n} ({r:.0%})" for n, r, _ in top)
        report.add("trigger/overlap", "WARN",
                   f"Description overlaps with: {details}", 1)
    else:
        report.add("trigger/overlap", "PASS", "No significant trigger overlap detected")


def run_health_check(skill_path: str) -> HealthReport:
    skill_dir = Path(skill_path)

    skill_md = skill_dir / "SKILL.md"
    name = skill_dir.name
    if skill_md.exists():
        content = skill_md.read_text(encoding='utf-8', errors='replace')
        fm = parse_frontmatter(content)
        if fm and 'name' in fm:
            name = fm['name']
    else:
        content = ""
        fm = None

    report = HealthReport(skill_name=name, skill_path=str(skill_dir))

    check_structure(skill_dir, report)
    if content:
        check_references(skill_dir, content, report)
        check_instruction_quality(content, report)
    check_scripts(skill_dir, report)
    if fm:
        check_trigger_overlap(skill_dir, fm, report)

    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python health_check.py /path/to/skill-dir [--json]")
        sys.exit(1)

    skill_path = sys.argv[1]
    use_json = "--json" in sys.argv

    if not os.path.isdir(skill_path):
        print(f"Error: {skill_path} is not a directory")
        sys.exit(1)

    report = run_health_check(skill_path)

    if use_json:
        print(report.to_json())
    else:
        print(report.to_text())
