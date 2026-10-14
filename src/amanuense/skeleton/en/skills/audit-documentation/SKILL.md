---
name: audit-documentation
description: Compares the Confluence export with the local documentation and proposes how to make it consistent and lean. Use it before rewriting pages or when someone asks what is redundant, missing or duplicated.
---

# Audit the documentation

## Inputs

- Workshop folder with `1-confluence-export/`, `2-my-docs/` and `3-bible/`.

## Steps

1. Run the workshop (`amanuense.bat` on Windows, `./amanuense.sh` on Linux/macOS).
   If the environment has the search tool installed, add `--content`.
2. Read `output/report.md`.
3. Propose, in this order and without executing anything:
   - **Update**: the tasks in `output/tasks/*-update-*`.
   - **Create**: the ones in `*-new-*`.
   - **Merge**: each "Duplicates in local" and "Similar content under another title";
     say which one stays and what it takes from the other.
   - **Retire**: from "Only in Confluence", the pages nobody links to or that repeat another.
     They are candidates: the decision is human.
   - **Assign by hand**: "Instructions without a target page" (renamed page?).
4. For each contradiction, quote the two sentences and say which one the bible follows.

## Output

A short list with the five sections above and, at the end, how many pages
would remain in Confluence if everything is approved.

## Never

Delete, move or publish. This skill only proposes.
