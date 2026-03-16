---
name: skill-evolver
description: Monitor skill health, diagnose failures, and auto-improve skills. Use when a user reports a skill isn't working well, wants to check skill health, says "this skill keeps failing", "improve the docx skill", "why does X skill do Y wrong", or wants to run a health check on their skill system. Also triggers when the user says "evolve", "fix my skill", "skill is broken", "skill regression", or asks to analyze skill performance. Even if the user doesn't name a specific skill, trigger if they express frustration with output quality from a skill-powered task.
---

# Skill Evolver

A meta-skill that diagnoses skill failures, proposes targeted fixes, and verifies improvements — a closed-loop repair system for the skill ecosystem.

## Mental Model

Think of this as a **skill doctor** who triangulates multiple sources before diagnosing:

1. **Observe** — Examine execution artifacts objectively (the "blood test").
2. **Triage** — Gather the patient's self-report and complaints.
3. **Converge** — Cross-reference observation, self-report, and static analysis. Note discrepancies.
4. **Diagnose** — Form a judgment based on all evidence, not just one source.
5. **Treat** — Generate a minimal, targeted patch.
6. **Verify** — Re-run to confirm the fix works and nothing else broke.

The key principle: **never diagnose from a single source**. Agent self-reports may be incomplete or wrong. Static analysis checks the chart, not the patient. Only objective observation of execution artifacts reveals what actually happened.

Unlike skill-creator (which builds from scratch with heavy human-in-the-loop), skill-evolver is biased toward **autonomous diagnosis and surgical repair**.

### Coordination Primitives

This skill uses operations inspired by the [Synodic coordination model](https://github.com/codervisor/synodic):

- **observe()** — Read another agent's execution state through its artifacts, independent of self-reporting
- **converge()** — Detect agreement or discrepancy across multiple evidence sources
- **prune()** — Recommend retirement of skills that consistently fail and resist repair

---

## Phase 0: Observe

Before collecting anyone's opinion, examine the objective evidence. There are two complementary lenses available — use whichever data exists, ideally both.

### Lens 1: Session Transcript (the "blood test")

AI coding tools like Claude Code store complete session transcripts as JSONL files. These contain every tool call, every result, every error — the ground truth of what actually happened, independent of what the agent chose to report.

**Discover available transcripts:**

```bash
python <skill-base>/scripts/observe_execution.py --list-transcripts
```

Known transcript locations:
- Claude Code: `~/.claude/projects/<project-hash>/<session-id>.jsonl`
- Subagent transcripts: `~/.claude/projects/<project-hash>/<session-id>/subagents/agent-*.jsonl`

**Parse a transcript:**

```bash
python <skill-base>/scripts/observe_execution.py --transcript <session.jsonl> --skill-name <name> --json
```

This extracts from the raw runtime log:
- Every tool call the agent made and in what order
- Tool errors and failures (exit codes, exceptions, permission denials)
- Which skills were referenced during execution
- Token usage and session duration
- Event type distribution (how much time in tool use vs. thinking vs. user interaction)

### Lens 2: Workspace Artifacts (the "physical exam")

If the execution produced files in a workspace directory, scan them:

```bash
python <skill-base>/scripts/observe_execution.py <workspace-dir> --skill-name <name> --json
```

This produces an objective record of:
- What files were created and their sizes (empty files = likely silent failure)
- Error traces found in any output files
- Script logs, stderr captures, exit codes
- Token usage and timing if available

### Combining both lenses

When both a transcript and a workspace are available, use both:

```bash
python <skill-base>/scripts/observe_execution.py <workspace-dir> \
  --transcript <session.jsonl> --skill-name <name> --json
```

### Cross-reference with self-reports (convergence check)

Add `--compare-signal <skill-name>` to any of the above commands to compare the objective observation against what the agent self-reported via signal_log.py. Discrepancies are the most valuable diagnostic signal:

- **Errors in transcript/artifacts, no failure reported** → agent didn't recognize its own failure
- **Failure reported, no errors found** → agent may be mischaracterizing a correct outcome
- **Verified fix reported, errors still present** → fix was ineffective
- **Tools used but not reported** → agent's self-report is incomplete
- **Empty outputs despite execution signals** → skill ran but produced nothing useful

Save the observation:

```bash
python <skill-base>/scripts/signal_log.py record <skill-name> observation \
  '{"workspace": "...", "transcript": "...", "errors_found": [...], "discrepancies": [...]}'
```

**If neither transcript nor workspace is available**, skip to Phase 1 and note that diagnosis will rely on self-report only (lower confidence).

---

## Phase 1: Triage

Determine which skill is affected and what the symptoms are.

**If the user names a specific skill:**
- Locate it: check `~/.claude/skills/`, `.claude/skills/`, `.agent/skills/`, project skill directories
- Read its SKILL.md
- Ask for a concrete failing prompt (or extract from conversation history)

**If the user is vague ("output quality is bad"):**
- Look at recent conversation turns to identify which skill was likely invoked
- Ask the user to confirm

**If the user wants a health check (no specific failure):**
- Jump to the Static Analysis section, then offer targeted diagnosis if issues are found

## Phase 2: Diagnose

Reproduce the failure, cross-reference all evidence, then identify root cause. Resist the urge to jump to fixing.

**Step 2a: Reproduce**

Spawn a subagent to run the failing prompt, following the skill's instructions exactly as a fresh agent would. Direct the subagent's outputs to a clean workspace directory. This is the **spawn** operation — an isolated execution whose artifacts you can then observe.

After the subagent completes, **observe** its workspace:

```bash
python <skill-base>/scripts/observe_execution.py <workspace-dir> \
  --compare-signal <skill-name> --json
```

Capture from the observation:
- What files the execution actually produced
- What errors appear in the artifacts
- Where the output diverged from user expectation
- Discrepancies between observed state and any prior self-reports

**Step 2b: Converge — Cross-reference all evidence**

Before classifying, lay out what each source says:

| Source | What it says | Confidence |
|--------|-------------|------------|
| Observation (artifacts) | What actually happened | High — objective |
| Self-report (signals) | What the agent said happened | Medium — may be incomplete |
| Static analysis (health check) | Skill structure issues | Medium — checks form, not function |
| User report | What the user experienced | High — but may lack technical detail |

Look for **agreement** and **discrepancy**:
- If all sources agree → high confidence in diagnosis
- If observation contradicts self-report → trust the observation, investigate why the agent misreported
- If user report contradicts observation → the artifacts may not capture the full picture (e.g., UX issues)

**Step 2c: Root Cause Classification**

Classify into one of 8 types (see `references/root_cause_taxonomy.md` for full details):

- **instruction-gap** — skill doesn't cover this case
- **instruction-conflict** — contradictory guidance within the skill
- **instruction-overfit** — too rigid for valid input variation
- **tool-misuse** — incorrect tool usage instructions
- **dependency-drift** — external dependency changed
- **trigger-miss** — skill should have triggered but didn't
- **trigger-false** — wrong skill triggered
- **performance** — correct but slow/token-heavy

Each type maps to a different fix strategy. Read the taxonomy before choosing.

**Step 2d: Confirm with user**

Present your diagnosis with the evidence sources that support it. If observation and self-report disagree, show both and explain which you trust and why. If confident and the fix is small, proceed and show the diff after.

## Phase 3: Treat

Generate a targeted patch. Principle: **minimal effective change**.

1. Copy the skill to a writable location
2. Apply surgical edits (prefer `str_replace` over rewriting whole sections)
3. For each change: show before/after, explain why it addresses the root cause
4. If new scripts or resources are needed, add them to the skill's `scripts/` or `references/`

**Escalation rule:** if the fix requires changing >30% of SKILL.md, hand off to Anthropic's official skill-creator with a diagnosis report instead.

## Phase 4: Verify

Verification must use observation, not self-assessment. The agent applying the fix should not be the one judging if it worked.

**Level 1 — Regression check:** If existing evals exist, re-run them against the patched skill.

**Level 2 — Fix validation:** Spawn a fresh subagent to re-run the original failing prompt with the patched skill. Direct outputs to a new workspace. Then **observe** that workspace:

```bash
python <skill-base>/scripts/observe_execution.py <post-fix-workspace> \
  --compare-signal <skill-name> --json
```

The fix is verified only if:
- The observation shows no errors related to the original failure
- Output artifacts are non-empty and reasonable
- No new discrepancies between observation and self-report

Log results:

```bash
python <skill-base>/scripts/signal_log.py record <skill-name> fix \
  '{"patch": "...", "verified": true, "regressions": [], "observation": "..."}'
```

If verification fails after 2 attempts, escalate to the user with findings. Include both the self-report and the observation data so the user can see the full picture.

## Phase 5: Report & Package

Present results to the user concisely: skill name, issue, root cause type, what changed, verification status.

---

## Static Analysis (Health Check Mode)

Run without a specific failure. Use the health check script:

```bash
python <skill-base>/scripts/health_check.py /path/to/skill-dir
```

Or scan all installed skills:

```bash
cd <skill-base>/scripts && python scan_all.py
```

### What it checks

**Structure:** SKILL.md exists, valid frontmatter, description length, file references resolve

**Instruction quality:** excessive forceful language (MUST/NEVER/ALWAYS), hardcoded paths, missing error handling, contradictions, length

**Scripts:** shebangs, bare except clauses

**Triggers:** description overlap with other installed skills

### System-wide analysis

When checking the full ecosystem, also detect:
- Trigger overlap between skills (two skills competing for same prompts)
- Capability gaps (common needs not covered)
- Dependency conflicts

---

## Prune: When to Retire a Skill

Not every skill can be repaired. Use the **prune** operation when:

- 3+ fix attempts have failed for the same root cause
- Observation consistently shows errors that self-reports don't acknowledge
- The health rating is `unreliable-reporting` (agent self-reports don't match artifacts)
- The skill's domain is now covered better by another skill

**Prune actions (in order of severity):**

1. **Flag** — Add a warning to the skill's signal log and recommend review
2. **Disable** — Rename `SKILL.md` to `SKILL.md.disabled` to stop triggering
3. **Escalate** — Hand off to skill-creator for a full rebuild with diagnosis report

Always present the prune recommendation to the user with evidence. Never silently disable a skill.

---

## Integration with skill-creator

| Concern | skill-evolver | skill-creator |
|---------|---------------|---------------|
| Trigger | Something broken / degraded | Build from scratch / major rework |
| Scope | Surgical patch | Full skill lifecycle |
| Human involvement | Minimal | Heavy (interview, iterate, evaluate) |

When evolver determines the fix requires major rewrite, hand off to Anthropic's official skill-creator with:
- Skill name and path
- Diagnosis summary
- Failed fix attempts
- Structural recommendation
