---
name: skill-evolver
description: Monitor skill health, diagnose failures, and auto-improve skills. Use when a user reports a skill isn't working well, wants to check skill health, says "this skill keeps failing", "improve the docx skill", "why does X skill do Y wrong", or wants to run a health check on their skill system. Also triggers when the user says "evolve", "fix my skill", "skill is broken", "skill regression", or asks to analyze skill performance. Even if the user doesn't name a specific skill, trigger if they express frustration with output quality from a skill-powered task.
---

# Skill Evolver

A meta-skill that diagnoses skill failures, proposes targeted fixes, and verifies improvements — a closed-loop repair system for the skill ecosystem.

## Mental Model

Think of this as a **skill doctor**:

1. **Triage** — What's wrong? Gather symptoms.
2. **Diagnose** — Reproduce the failure, identify root cause.
3. **Treat** — Generate a minimal, targeted patch.
4. **Verify** — Re-run to confirm the fix works and nothing else broke.

Unlike skill-creator (which builds from scratch with heavy human-in-the-loop), skill-evolver is biased toward **autonomous diagnosis and surgical repair**.

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

Reproduce the failure and identify root cause. Resist the urge to jump to fixing.

**Step 2a: Reproduce**

Run the failing prompt yourself, following the skill's instructions exactly as a fresh agent would. Capture:

- What the skill told you to do
- What you actually did
- Where the output diverged from user expectation
- Any errors, retries, or dead ends

Save execution trace to `~/.skill-signals/<skill-name>/signals.jsonl` using the signal log script:

```bash
python <skill-base>/scripts/signal_log.py record <skill-name> failure \
  '{"prompt": "...", "symptoms": ["..."], "root_cause": "..."}'
```

**Step 2b: Root Cause Classification**

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

**Step 2c: Confirm with user**

Before fixing, explain your diagnosis concisely. If confident and the fix is small, proceed and show the diff after.

## Phase 3: Treat

Generate a targeted patch. Principle: **minimal effective change**.

1. Copy the skill to a writable location
2. Apply surgical edits (prefer `str_replace` over rewriting whole sections)
3. For each change: show before/after, explain why it addresses the root cause
4. If new scripts or resources are needed, add them to the skill's `scripts/` or `references/`

**Escalation rule:** if the fix requires changing >30% of SKILL.md, hand off to Anthropic's official skill-creator with a diagnosis report instead.

## Phase 4: Verify

**Level 1 — Regression check:** if existing evals exist, re-run them against the patched skill.

**Level 2 — Fix validation:** re-run the original failing prompt. Confirm the failure is resolved.

Log results:

```bash
python <skill-base>/scripts/signal_log.py record <skill-name> fix \
  '{"patch": "...", "verified": true, "regressions": []}'
```

If verification fails after 2 attempts, escalate to the user with findings.

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
