# Brick IHM — documentation, agents and skills

Shared team repo for everything an AI writes or reads. Confluence (MIND)
remains the published source of truth. This repo holds its working copy,
the rules, and the procedures to keep it up to date.

```
docs/
  bible/         what rules: reference architecture, Nexus publishing,
                 repo standards. If anything contradicts it, this wins.
  common/        documentation shared by all bricks (processes, naming,
                 day-to-day templates, guides).
  brick-hmi/     documentation specific to Brick IHM, one page per file,
                 with the same title as its Confluence page.
agents/          one file per role: who does what, with which skills and which approval.
skills/          one procedure per folder (SKILL.md): steps, inputs, outputs.
AGENTS.md        rules every agent reads before touching the repo.
```

## Agents and skills in each tool

`skills/` and `agents/` are the only source: edit them there. To make each
tool find them in its own format, regenerate them with:

```
amanuense agents REPO_PATH
```

| Tool | Skills | Agent | Instructions |
| --- | --- | --- | --- |
| Claude Code | `.claude/skills/` | `.claude/agents/` | `CLAUDE.md` → `@AGENTS.md` |
| Codex | `.agents/skills/` | `.codex/agents/*.toml` | `AGENTS.md` |
| Gemini CLI | `.agents/skills/` | `.gemini/agents/` | `AGENTS.md` (via `.gemini/settings.json`) |
| GitHub Copilot | `.agents/skills/` | `.github/agents/` | `AGENTS.md` |

This skeleton already ships with them generated. Open the repo with any of
these tools and ask, for example, "use the audit-documentation skill".

## How to work

1. Export the Confluence section to Word and run it through the workshop
   (`amanuense.bat`, see the amanuense guide) together with `docs/`.
2. The report says what to update, what is new and what is redundant.
3. Each page is rewritten with the right skill and goes through your approval
   (`CHANGES.html`) before it is pasted into Confluence.
4. The approved version is saved here, in `docs/`, with one commit per page.

## Non-negotiable rules

- Nothing is published to Confluence without human approval.
- No AI invents data: whatever is missing stays as `> PENDING`.
- One page, one topic: if something is already on another page, link it, do not copy it.
- Rule changes go to `AGENTS.md` or to the `SKILL.md`, not to the chat:
  that way every person and every agent gets the same result.
