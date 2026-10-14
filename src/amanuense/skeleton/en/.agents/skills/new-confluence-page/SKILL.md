---
name: new-confluence-page
description: Turns a local draft into a new Confluence page, using the team template when the draft asks for it ("Template: yes"). Use it with each output/tasks/*-new-* folder of the workshop and for capability designs ready to paste.
---

# New Confluence page

## Inputs

- A workshop task folder: `TASK.md` and `LOCAL.md`.
- If the draft has `Template: yes`, `TASK.md` includes the template.

## Steps

1. Read all of `TASK.md`. Its rules override this skill.
2. If there is a template: use its sections in its order. Fill each one only with
   what the draft or the bible says; the rest gets `> PENDING:`. The template's
   example values are not data.
3. If there is no template: keep the draft's structure and improve the wording.
4. Check that the page does not repeat an existing one; if it does, link it.
5. Add `## Change log`.
6. Save the result as `RESULT.md` and run the workshop again.
7. If `CHANGES.html` lists "Data without a source", replace each item with `> PENDING:`.

## Output

`RESULT.md` and, after running the workshop, `FOR-CONFLUENCE.html` to paste.

## Never

Fill template sections with guesses just to make the page "look complete".
A `PENDING` section is better than a false fact.
