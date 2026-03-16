#!/usr/bin/env python3
"""
skill-evolver: observe_execution.py
Artifact-based observation of skill execution — the "blood test" complement
to agent self-reporting.

Inspects a workspace directory where a skill execution produced artifacts,
and builds an objective observation record: what files were created/modified,
script exit codes, output sizes, error traces, and timing.

This implements the observe() primitive from the Synodic coordination model:
one agent reads another agent's execution state through its artifacts,
independent of what the executing agent chose to self-report.

Usage:
  python observe_execution.py <workspace-dir> [--skill-name NAME] [--json]
  python observe_execution.py <workspace-dir> --compare-signal <skill-name>
"""

import sys
import os
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict


SIGNAL_DIR = Path.home() / ".skill-signals"


@dataclass
class ArtifactObservation:
    path: str
    size_bytes: int
    is_empty: bool
    modified: str


@dataclass
class ScriptObservation:
    script: str
    has_output: bool
    stderr_present: bool
    exit_code_file: str = None
    error_snippets: list = field(default_factory=list)


@dataclass
class ExecutionObservation:
    """Objective record of what a skill execution actually produced."""
    workspace: str
    skill_name: str
    observed_at: str
    artifacts: list = field(default_factory=list)
    scripts: list = field(default_factory=list)
    errors_found: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    discrepancies: list = field(default_factory=list)

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    def to_text(self):
        lines = [
            f"Execution Observation: {self.skill_name}",
            f"Workspace: {self.workspace}",
            f"Observed at: {self.observed_at}",
            "━" * 50,
        ]

        lines.append(f"\nArtifacts: {len(self.artifacts)} files")
        for a in self.artifacts:
            empty_tag = " [EMPTY]" if a["is_empty"] else ""
            lines.append(f"  {a['path']} ({a['size_bytes']} bytes){empty_tag}")

        if self.scripts:
            lines.append(f"\nScripts: {len(self.scripts)} observed")
            for s in self.scripts:
                status = "stderr present" if s["stderr_present"] else "clean"
                lines.append(f"  {s['script']}: {status}")
                for err in s.get("error_snippets", []):
                    lines.append(f"    > {err[:120]}")

        if self.errors_found:
            lines.append(f"\nErrors: {len(self.errors_found)}")
            for e in self.errors_found:
                lines.append(f"  - {e}")

        if self.warnings:
            lines.append(f"\nWarnings: {len(self.warnings)}")
            for w in self.warnings:
                lines.append(f"  - {w}")

        if self.metrics:
            lines.append("\nMetrics:")
            for k, v in self.metrics.items():
                lines.append(f"  {k}: {v}")

        if self.discrepancies:
            lines.append(f"\nDiscrepancies (observation vs self-report): {len(self.discrepancies)}")
            for d in self.discrepancies:
                lines.append(f"  ! {d}")

        return "\n".join(lines)


def observe_artifacts(workspace: Path) -> list:
    """Scan workspace for output artifacts."""
    artifacts = []
    if not workspace.exists():
        return artifacts

    for f in sorted(workspace.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            try:
                stat = f.stat()
                artifacts.append(ArtifactObservation(
                    path=str(f.relative_to(workspace)),
                    size_bytes=stat.st_size,
                    is_empty=stat.st_size == 0,
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                ))
            except OSError:
                continue

    return artifacts


def observe_scripts(workspace: Path) -> list:
    """Look for script execution traces: logs, stderr, exit codes."""
    observations = []

    # Check for common log patterns
    log_patterns = ["*.log", "*.err", "*.stderr", "*.stdout", "*.exitcode"]
    log_files = []
    for pat in log_patterns:
        log_files.extend(workspace.rglob(pat))

    # Also check for output captures in known locations
    for log_file in sorted(set(log_files)):
        obs = ScriptObservation(
            script=str(log_file.relative_to(workspace)),
            has_output=log_file.stat().st_size > 0,
            stderr_present="stderr" in log_file.name or "err" in log_file.suffix,
        )

        if obs.stderr_present and obs.has_output:
            try:
                content = log_file.read_text(errors="replace")
                # Extract error-like lines
                for line in content.splitlines():
                    if re.search(r'(?i)(error|exception|traceback|failed|fatal)', line):
                        obs.error_snippets.append(line.strip())
                        if len(obs.error_snippets) >= 5:
                            break
            except OSError:
                pass

        observations.append(obs)

    return observations


def scan_for_errors(workspace: Path) -> list:
    """Scan all text files for error indicators."""
    errors = []
    error_pattern = re.compile(
        r'(?i)(traceback|error:|exception:|fatal:|failed to|could not|permission denied|no such file)'
    )

    for f in workspace.rglob("*"):
        if not f.is_file() or f.stat().st_size > 1_000_000:  # skip large files
            continue
        if f.suffix in ('.pyc', '.so', '.o', '.bin', '.png', '.jpg', '.pdf'):
            continue

        try:
            content = f.read_text(errors="replace")
            for i, line in enumerate(content.splitlines(), 1):
                if error_pattern.search(line):
                    rel = f.relative_to(workspace)
                    errors.append(f"{rel}:{i}: {line.strip()[:150]}")
                    if len(errors) >= 20:
                        return errors
        except (OSError, UnicodeDecodeError):
            continue

    return errors


def collect_metrics(workspace: Path, artifacts: list) -> dict:
    """Derive objective metrics from the workspace."""
    metrics = {}

    metrics["total_files"] = len(artifacts)
    metrics["total_bytes"] = sum(a.size_bytes for a in artifacts)
    metrics["empty_files"] = sum(1 for a in artifacts if a.is_empty)

    # Check for timing data (if the execution left timing info)
    timing_files = list(workspace.rglob("timing.json"))
    for tf in timing_files:
        try:
            data = json.loads(tf.read_text())
            if "duration_ms" in data:
                metrics["duration_ms"] = data["duration_ms"]
            if "total_tokens" in data:
                metrics["total_tokens"] = data["total_tokens"]
        except (json.JSONDecodeError, OSError):
            pass

    return metrics


def compare_with_signals(skill_name: str, observation: ExecutionObservation) -> list:
    """Cross-reference observation with self-reported signals.

    This is the convergence check: do the agent's self-reports
    match what we objectively observe in the artifacts?
    """
    discrepancies = []
    signal_file = SIGNAL_DIR / skill_name / "signals.jsonl"

    if not signal_file.exists():
        discrepancies.append(
            "No self-reported signals found — agent may not be logging executions"
        )
        return discrepancies

    # Read recent signals (last 10)
    signals = []
    with open(signal_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    signals = signals[-10:]

    if not signals:
        discrepancies.append("Signal file exists but contains no valid entries")
        return discrepancies

    # Check: are there errors in artifacts but no failure signals?
    recent_failures = [s for s in signals if s.get("type") == "failure"]
    if observation.errors_found and not recent_failures:
        discrepancies.append(
            f"Observation found {len(observation.errors_found)} error(s) in artifacts, "
            f"but no failure signals were self-reported"
        )

    # Check: failure signals exist but no errors in artifacts?
    if recent_failures and not observation.errors_found:
        discrepancies.append(
            f"{len(recent_failures)} failure(s) self-reported, "
            f"but no errors found in workspace artifacts — "
            f"agent may be mischaracterizing outcomes"
        )

    # Check: empty output files suggest silent failure
    if observation.metrics.get("empty_files", 0) > 0:
        empty_count = observation.metrics["empty_files"]
        has_execution_signals = any(s.get("type") == "execution" for s in signals)
        if has_execution_signals:
            discrepancies.append(
                f"{empty_count} empty output file(s) found despite execution signals — "
                f"skill may have run but produced no useful output"
            )

    # Check: are there fix signals but errors persist?
    recent_fixes = [s for s in signals if s.get("type") == "fix" and s.get("verified")]
    if recent_fixes and observation.errors_found:
        discrepancies.append(
            f"Verified fix was reported, but errors still present in artifacts — "
            f"fix may not have been effective"
        )

    return discrepancies


def observe(workspace_path: str, skill_name: str = None,
            compare_signals: bool = False) -> ExecutionObservation:
    """Main observation entry point.

    Examines a workspace directory and builds an objective record
    of what the skill execution produced.
    """
    workspace = Path(workspace_path)
    if not skill_name:
        skill_name = workspace.name

    raw_artifacts = observe_artifacts(workspace)
    raw_scripts = observe_scripts(workspace)
    errors = scan_for_errors(workspace)
    metrics = collect_metrics(workspace, raw_artifacts)

    # Build warnings from objective observations
    warnings = []
    if not raw_artifacts:
        warnings.append("No output artifacts found in workspace")
    if metrics.get("empty_files", 0) > metrics.get("total_files", 1) * 0.5:
        warnings.append("More than half of output files are empty")
    if metrics.get("total_tokens", 0) > 100000:
        warnings.append(f"High token usage: {metrics['total_tokens']}")

    observation = ExecutionObservation(
        workspace=str(workspace),
        skill_name=skill_name,
        observed_at=datetime.utcnow().isoformat() + "Z",
        artifacts=[asdict(a) for a in raw_artifacts],
        scripts=[asdict(s) for s in raw_scripts],
        errors_found=errors,
        warnings=warnings,
        metrics=metrics,
    )

    if compare_signals and skill_name:
        observation.discrepancies = compare_with_signals(skill_name, observation)

    return observation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Observe skill execution artifacts objectively"
    )
    parser.add_argument("workspace", help="Path to workspace/output directory")
    parser.add_argument("--skill-name", help="Skill name (defaults to directory name)")
    parser.add_argument("--compare-signal",
                        help="Compare observation against self-reported signals for this skill",
                        metavar="SKILL_NAME")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    skill = args.compare_signal or args.skill_name
    obs = observe(
        args.workspace,
        skill_name=skill,
        compare_signals=bool(args.compare_signal),
    )

    if args.json:
        print(obs.to_json())
    else:
        print(obs.to_text())
