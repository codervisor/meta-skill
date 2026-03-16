# Root Cause Taxonomy

When skill-evolver diagnoses a failure, it classifies into one of these types. Each type maps to a different fix strategy.

## instruction-gap

**Signal**: The skill doesn't cover this case at all. The agent had to improvise or failed silently.

**Example**: User asks docx skill to insert a chart, but the skill has no chart instructions.

**Fix pattern**: Add a new section to SKILL.md covering the missing case. Keep it minimal — just enough for the agent to handle it correctly.

**Risk**: Low. Adding new instructions rarely breaks existing behavior.

## instruction-conflict

**Signal**: Two parts of the skill give contradictory guidance. The agent followed one and violated the other.

**Example**: Skill says "always use tables for data" and later "avoid tables in executive summaries."

**Fix pattern**: Resolve by adding priority rules or scoping each instruction to its context. Don't just delete one — both probably exist for a reason.

**Risk**: Medium. Changing conflict resolution can affect multiple use cases.

## instruction-overfit

**Signal**: Skill is too rigid for valid input variation. Works for the template case but fails on real-world input.

**Example**: Skill expects CSV with header row, but user's CSV has metadata rows before the header.

**Fix pattern**: Generalize the relevant section. Add detection/branching logic instead of hardcoded assumptions.

**Risk**: Medium. Generalizing can introduce ambiguity if not careful.

## tool-misuse

**Signal**: Skill tells the agent to use a tool incorrectly — wrong arguments, wrong sequence, wrong tool for the job.

**Example**: Skill says to use `str_replace` on a binary file, or calls a Python library with deprecated API.

**Fix pattern**: Fix the specific tool usage instruction. Test the corrected usage in isolation.

**Risk**: Low if the fix is localized to one tool call.

## dependency-drift

**Signal**: External dependency changed — library API, file format, platform behavior, service endpoint.

**Example**: Skill uses `python-docx` API that was deprecated in a newer version installed in the environment.

**Fix pattern**: Update dependency-specific instructions. Pin versions if stability matters. Add version detection if multiple versions must be supported.

**Risk**: High if the dependency change is fundamental. May require structural rewrite.

## trigger-miss

**Signal**: Skill should have triggered but didn't. User's prompt clearly needed this skill, but the description didn't match.

**Example**: User says "make me a slide deck" but the pptx skill only triggers on "presentation" and ".pptx".

**Fix pattern**: Expand the description with more trigger phrases. Use skill-creator's description optimizer if available.

**Risk**: Low for the skill itself. Watch for increased trigger overlap with other skills.

## trigger-false

**Signal**: Wrong skill triggered. User's prompt matched this skill's description but actually needed a different one.

**Example**: User says "create a report" and docx skill triggers, but user wanted a PDF report.

**Fix pattern**: Narrow the description. Add explicit exclusions. May need to coordinate with the other skill's description.

**Risk**: Medium. Narrowing can cause trigger-miss for legitimate cases.

## performance

**Signal**: Skill works correctly but uses too many tokens, takes too many steps, or runs too slowly.

**Example**: Skill reads the entire file to make a one-line change, or retries operations unnecessarily.

**Fix pattern**: Optimize the workflow. Remove unnecessary steps, add early exits, batch operations.

**Risk**: Low-medium. Optimization can sometimes break edge cases.

---

## Escalation Criteria

Escalate from skill-evolver to skill-creator when:

- The root cause requires changing >30% of the SKILL.md
- Multiple root cause types are present simultaneously
- The fix requires restructuring the skill's overall architecture
- Two failed fix attempts for the same root cause
- The skill lacks basic structure (no frontmatter, no clear workflow)
