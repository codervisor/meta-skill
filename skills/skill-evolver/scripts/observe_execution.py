#!/usr/bin/env python3
"""
skill-evolver: observe_execution.py
Objective observation of skill execution through two complementary lenses:

1. Artifact observation — scan workspace for output files, errors, script traces
2. Transcript observation — parse AI tool runtime logs (JSONL session transcripts)
   to extract the actual sequence of tool calls, errors, and outcomes

Together these form the observe() primitive from the Synodic coordination model:
read another agent's execution state independent of self-reporting.

Usage:
  python observe_execution.py <workspace-dir> [--skill-name NAME] [--json]
  python observe_execution.py <workspace-dir> --compare-signal <skill-name>
  python observe_execution.py --transcript <session.jsonl> [--skill-name NAME] [--json]
  python observe_execution.py --transcript <session.jsonl> --compare-signal <skill-name>
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
class TranscriptObservation:
    """Objective record extracted from an AI tool's session transcript."""
    source: str
    total_events: int
    tool_calls: list = field(default_factory=list)
    tool_errors: list = field(default_factory=list)
    skill_references: list = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    duration_ms: int = 0
    event_type_counts: dict = field(default_factory=dict)


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
    transcript: dict = field(default_factory=dict)

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

        if self.transcript:
            lines.append("\nTranscript Analysis:")
            lines.append(f"  Source: {self.transcript.get('source', 'unknown')}")
            lines.append(f"  Events: {self.transcript.get('total_events', 0)}")
            evt_counts = self.transcript.get("event_type_counts", {})
            if evt_counts:
                lines.append(f"  Event types: {evt_counts}")
            tc = self.transcript.get("tool_calls", [])
            if tc:
                lines.append(f"  Tool calls: {len(tc)}")
                for t in tc[:15]:
                    status = f" [ERROR: {t.get('error', '')[:80]}]" if t.get("error") else ""
                    lines.append(f"    {t['tool']}{status}")
            te = self.transcript.get("tool_errors", [])
            if te:
                lines.append(f"  Tool errors: {len(te)}")
                for e in te[:10]:
                    lines.append(f"    - {e['tool']}: {e['error'][:120]}")
            sr = self.transcript.get("skill_references", [])
            if sr:
                lines.append(f"  Skills referenced: {', '.join(sr)}")
            tok = self.transcript.get("token_usage", {})
            if tok:
                lines.append(f"  Tokens: {tok}")

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


def parse_transcript(transcript_path: Path, skill_name: str = None) -> TranscriptObservation:
    """Parse an AI tool's JSONL session transcript.

    Extracts tool calls, errors, token usage, and skill references
    from Claude Code (or compatible) session transcripts.

    This is the core of observe() — reading the agent's actual execution
    trace rather than relying on what it chose to report.
    """
    events = []
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    obs = TranscriptObservation(
        source=str(transcript_path),
        total_events=len(events),
    )

    # Count event types
    type_counts = {}
    for evt in events:
        evt_type = evt.get("type", "unknown")
        type_counts[evt_type] = type_counts.get(evt_type, 0) + 1
    obs.event_type_counts = type_counts

    # Extract tool calls and their results
    # Claude Code stores tool_use and tool_result as separate events,
    # and also nests them inside assistant message content blocks
    tool_use_map = {}  # id -> tool info

    for evt in events:
        # Direct tool_use events
        if evt.get("type") == "tool_use":
            tool_id = evt.get("tool_use_id") or evt.get("id")
            tool_name = evt.get("tool_name") or evt.get("name", "unknown")
            tool_use_map[tool_id] = {"tool": tool_name, "id": tool_id}

        # Tool uses nested in assistant message content blocks
        if evt.get("type") in ("assistant", "message"):
            for block in evt.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_id = block.get("id")
                    tool_name = block.get("name", "unknown")
                    tool_use_map[tool_id] = {"tool": tool_name, "id": tool_id}

        # Tool results — match back to tool calls
        if evt.get("type") == "tool_result":
            tool_id = evt.get("tool_use_id")
            if tool_id and tool_id in tool_use_map:
                result = evt.get("content", "")
                if isinstance(result, list):
                    result = " ".join(
                        b.get("text", "") for b in result if isinstance(b, dict)
                    )
                result_str = str(result)
                is_error = evt.get("is_error", False)
                if is_error or re.search(
                    r'(?i)(error|traceback|exception|failed)', result_str[:500]
                ):
                    error_snippet = result_str[:200]
                    tool_use_map[tool_id]["error"] = error_snippet

    obs.tool_calls = list(tool_use_map.values())
    obs.tool_errors = [t for t in obs.tool_calls if t.get("error")]

    # Extract token usage from message events
    total_input = 0
    total_output = 0
    for evt in events:
        usage = evt.get("usage", {})
        if not usage and evt.get("type") == "message":
            usage = evt.get("usage", {})
        if usage:
            total_input += usage.get("input_tokens", 0)
            total_output += usage.get("output_tokens", 0)

    if total_input or total_output:
        obs.token_usage = {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total": total_input + total_output,
        }

    # Detect skill references in the transcript
    skill_refs = set()
    skill_pattern = re.compile(r'skills?/([a-zA-Z0-9_-]+)/SKILL\.md')
    for evt in events:
        content = json.dumps(evt)
        for match in skill_pattern.finditer(content):
            skill_refs.add(match.group(1))
    obs.skill_references = sorted(skill_refs)

    # Calculate duration from first to last event timestamps
    timestamps = []
    for evt in events:
        ts = evt.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                timestamps.append(dt)
            except ValueError:
                continue
    if len(timestamps) >= 2:
        duration = (max(timestamps) - min(timestamps)).total_seconds() * 1000
        obs.duration_ms = int(duration)

    return obs


def find_transcripts(skill_name: str = None) -> list:
    """Discover session transcripts from known AI tool log locations.

    Searches Claude Code's standard storage paths. Can be extended
    for other tools (Codex, Copilot, etc.) that store JSONL transcripts.
    """
    transcript_paths = []
    home = Path.home()

    # Claude Code: ~/.claude/projects/<project-hash>/<session-id>.jsonl
    claude_projects = home / ".claude" / "projects"
    if claude_projects.exists():
        for project_dir in claude_projects.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in sorted(project_dir.glob("*.jsonl"), reverse=True):
                transcript_paths.append(jsonl_file)
            # Also check subagent transcripts
            for session_dir in project_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                subagents_dir = session_dir / "subagents"
                if subagents_dir.exists():
                    for sa_file in sorted(subagents_dir.glob("*.jsonl"), reverse=True):
                        transcript_paths.append(sa_file)

    return transcript_paths


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

    # Check transcript data against signals if available
    transcript = observation.transcript
    if transcript:
        tool_errors = transcript.get("tool_errors", [])
        if tool_errors and not recent_failures:
            discrepancies.append(
                f"Transcript shows {len(tool_errors)} tool error(s), "
                f"but no failure signals were self-reported"
            )

        reported_tools = set()
        for s in signals:
            if s.get("type") == "execution":
                for t in s.get("tools_used", []):
                    reported_tools.add(t)
        if reported_tools:
            actual_tools = {t["tool"] for t in transcript.get("tool_calls", [])}
            unreported = actual_tools - reported_tools
            if unreported:
                discrepancies.append(
                    f"Tools used but not reported: {', '.join(sorted(unreported))}"
                )

    return discrepancies


def observe(workspace_path: str = None, skill_name: str = None,
            compare_signals: bool = False,
            transcript_path: str = None) -> ExecutionObservation:
    """Main observation entry point.

    Examines execution through two complementary lenses:
    1. Workspace artifacts — files, logs, errors on disk
    2. Session transcript — the actual tool calls and results from the AI runtime

    Either or both can be provided. Together they give the fullest picture.
    """
    workspace = Path(workspace_path) if workspace_path else None
    if not skill_name:
        if workspace:
            skill_name = workspace.name
        elif transcript_path:
            skill_name = Path(transcript_path).stem
        else:
            skill_name = "unknown"

    raw_artifacts = []
    raw_scripts = []
    errors = []
    metrics = {}
    warnings = []

    # Lens 1: Workspace artifacts
    if workspace and workspace.exists():
        raw_artifacts = observe_artifacts(workspace)
        raw_scripts = observe_scripts(workspace)
        errors = scan_for_errors(workspace)
        metrics = collect_metrics(workspace, raw_artifacts)

        if not raw_artifacts:
            warnings.append("No output artifacts found in workspace")
        if metrics.get("empty_files", 0) > metrics.get("total_files", 1) * 0.5:
            warnings.append("More than half of output files are empty")
        if metrics.get("total_tokens", 0) > 100000:
            warnings.append(f"High token usage: {metrics['total_tokens']}")

    # Lens 2: Session transcript
    transcript_data = {}
    if transcript_path:
        tp = Path(transcript_path)
        if tp.exists():
            transcript_obs = parse_transcript(tp, skill_name)
            transcript_data = asdict(transcript_obs)

            # Merge transcript metrics into main metrics
            if transcript_obs.token_usage:
                metrics["transcript_tokens"] = transcript_obs.token_usage.get("total", 0)
            if transcript_obs.duration_ms:
                metrics["transcript_duration_ms"] = transcript_obs.duration_ms

            # Transcript-derived warnings
            if transcript_obs.tool_errors:
                n = len(transcript_obs.tool_errors)
                warnings.append(f"Transcript contains {n} tool error(s)")
            if transcript_obs.token_usage.get("total", 0) > 100000:
                warnings.append(
                    f"High token usage in transcript: "
                    f"{transcript_obs.token_usage['total']}"
                )
        else:
            warnings.append(f"Transcript file not found: {transcript_path}")

    observation = ExecutionObservation(
        workspace=str(workspace) if workspace else "",
        skill_name=skill_name,
        observed_at=datetime.utcnow().isoformat() + "Z",
        artifacts=[asdict(a) for a in raw_artifacts],
        scripts=[asdict(s) for s in raw_scripts],
        errors_found=errors,
        warnings=warnings,
        metrics=metrics,
        transcript=transcript_data,
    )

    if compare_signals and skill_name:
        observation.discrepancies = compare_with_signals(skill_name, observation)

    return observation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Observe skill execution through artifacts and/or session transcripts"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace/output directory")
    parser.add_argument("--transcript",
                        help="Path to JSONL session transcript (e.g. Claude Code session log)")
    parser.add_argument("--skill-name", help="Skill name (defaults to directory name)")
    parser.add_argument("--compare-signal",
                        help="Compare observation against self-reported signals for this skill",
                        metavar="SKILL_NAME")
    parser.add_argument("--list-transcripts", action="store_true",
                        help="List discovered session transcripts and exit")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.list_transcripts:
        transcripts = find_transcripts()
        if transcripts:
            for t in transcripts[:20]:
                size = t.stat().st_size
                print(f"  {t} ({size:,} bytes)")
        else:
            print("No session transcripts found.")
        sys.exit(0)

    if not args.workspace and not args.transcript:
        parser.error("Provide a workspace directory, --transcript path, or both")

    skill = args.compare_signal or args.skill_name
    obs = observe(
        workspace_path=args.workspace,
        skill_name=skill,
        compare_signals=bool(args.compare_signal),
        transcript_path=args.transcript,
    )

    if args.json:
        print(obs.to_json())
    else:
        print(obs.to_text())
