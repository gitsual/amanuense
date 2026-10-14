# Rules for agents

Read this before reading or writing in this repo.

## Sources, in order of authority

1. `docs/bible/`: reference architecture, publishing requirements, standards.
2. The page published in Confluence (the most recent export).
3. `docs/common/` and `docs/brick-hmi/`.
4. What the person says in the conversation.

If two sources clash, do not pick one: write `> CONFLICT: what clashes with what` and continue.

## When writing documentation

- Do not invent names, versions, URLs, dates, owners or procedures.
  Whatever is missing goes as `> PENDING: what is missing`.
- Apply only what is asked; keep everything else as it is.
- One page, one topic. If a block already lives on another page, link it.
- Markdown with the page title as `# Title`; tables in Markdown.
- End every rewritten page with `## Change log`.

## What you never do without explicit approval

- Publish or edit in Confluence, SharePoint, Jira or Bitbucket.
- Delete a page or a document.
- Change `docs/bible/`.

## Available skills

| Skill | Purpose |
| --- | --- |
| `skills/audit-documentation` | Compare Confluence with the local docs and propose how to reduce them |
| `skills/update-confluence-page` | Rewrite a page by applying its update instructions |
| `skills/new-confluence-page` | Turn a draft into a new page, with a template if requested |
