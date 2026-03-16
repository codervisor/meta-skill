# meta-skill

Meta-skills for the agent skill ecosystem. Skills that operate on skills themselves.

## Install

```bash
npx skills add codervisor/meta-skill
```

## Skills

| Skill | Purpose | Meta Level |
|-------|---------|------------|
| **skill-evolver** | Diagnose, repair, and monitor skill health | L2 — operates on skills |

For skill creation, use Anthropic's official [skill-creator](https://github.com/anthropics/courses/tree/master/skill-creator). skill-evolver handles the other half of the lifecycle: keeping skills alive and healthy after they're built.

## Architecture

```
L2: meta-skills
     ├── skill-creator (official)  → skill birth
     └── skill-evolver (this repo) → skill survival
          ├── diagnose   → root cause classification (8 types)
          ├── repair     → minimal targeted patch
          ├── verify     → regression + fix validation
          └── monitor    → signal logging + ecosystem health check
L1: domain skills (docx, pdf, xlsx, ...)
L0: atomic tools (bash, view, web_search, ...)
```

When skill-evolver determines a fix requires >30% rewrite, it escalates to skill-creator with a diagnosis report.

## Philosophy

- **Don't duplicate official tools.** skill-creator already exists. This repo fills the gap it doesn't cover: post-deployment health.
- **Reliability over orchestration.** Improving single-skill success rate from 90% to 99% matters more than building a skill mesh.
- **Level 2 is the practical ceiling.** Self-modification (L3) needs external feedback anchors that don't exist yet.

## Related

- [codervisor/lean-spec](https://github.com/codervisor/lean-spec) — Specification-Driven Development
- [skills.sh](https://skills.sh) — Open agent skills ecosystem

## License

MIT
