---
name: update-confluence-page
description: Rewrites a Confluence page applying only its "Update instructions", without inventing anything, and leaves it ready to approve and paste. Use it with each output/tasks/*-update-* folder of the workshop.
---

# Update a Confluence page

## Inputs

- A workshop task folder: `TASK.md` (rules, instructions, current page
  and bible), `CURRENT.md` and `LOCAL.md`.

## Steps

1. Read all of `TASK.md`. Its rules override this skill.
2. List the changes the instructions ask for. Nothing else changes.
3. Rewrite the page starting from `CURRENT.md` and apply only that list.
4. Check the result against the bible; if something clashes, write `> CONFLICT:` and keep the current text.
5. Remove repetition inside the page; if a block lives elsewhere, link it.
6. Add `## Change log` with one bullet per change.
7. Save the result as `RESULT.md` in the task folder.
8. Run the workshop again to generate `CHANGES.html` and `FOR-CONFLUENCE.html`.
9. If `CHANGES.html` lists "Data without a source", remove or justify each item before handing it over.

## Output

`RESULT.md`. The person reviews `CHANGES.html` and, if approved, pastes
`FOR-CONFLUENCE.html` into Confluence.

## Never

Publish to Confluence yourself, or fill in data that is not in the task.
