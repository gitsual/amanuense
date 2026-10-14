# amanuense: documentation workshop guide

The workshop speaks English by default. Use `--lang es` or `AMANUENSE_LANG=es` to switch it to Spanish (folder names, tasks and pages). A workshop that already has the Spanish folders keeps working in Spanish on its own. The Spanish guide is `docs/guia.md`.

It rewrites and updates Confluence pages from two sources:
the latest "Export to Word" of the section and your local working folder.
Everything runs on your computer; nothing is uploaded anywhere.

## What it does

1. It compares the export with your folder and writes a **report**: which pages
   need updating, which are new, what is duplicated, what conflicts, and which
   Confluence pages have no local equivalent (candidates to delete or merge).
2. It prepares **one task per page** (`TASK.md`) with everything an AI needs:
   rules, update instructions, the current page, the template and the bible.
3. When you save the AI's answer as `RESULT.md`, it generates
   `CHANGES.html` (what changes, for you to approve) and `FOR-CONFLUENCE.html`
   (open it → select all → copy → paste into Confluence).
4. It flags **data without a source**: figures, versions, acronyms, names or
   identifiers in the result that do not appear anywhere in what the AI received.
   They show at the top of `CHANGES.html` and in the index. They do not depend on
   the AI you use: check them first, before approving.

The template for new pages is given to the AI empty (titles and labels only), so
that the example values in the template do not end up in the new page.

## Try it in five minutes (Windows)

You only need Python 3.11 or newer (python.org). Ticking "Add python.exe to PATH" helps, but the
launcher also finds Python without it; some installers do not even show the box. If a folder in a path
has brackets, such as `[HMI]`, write the path in quotes in the terminal: `cd "C:\code\[HMI] docs"`.

1. Double-click **`amanuense.bat`** (in the root of the repo). The first time, it creates
   `Documents\docs-workshop` and opens the folder.
2. Fill in the folders:
   - `1-confluence-export\`: the exported Word file (page "···" menu →
     Export → Export to Word → "This page and its children").
   - `2-my-docs\`: your folder (.docx, .md or .txt). Whatever replaces a
     page has **the same title** and a paragraph that starts with
     `Update instructions:`. New material does not have one; if a new page
     must follow the template (a capability, for example), add the line
     `Template: yes`.
   - `3-bible\`: whatever overrides everything else (reference architecture,
     Nexus publishing requirements, repo standards). A document with
     "template" in its name becomes the template for new pages.
3. Double-click `amanuense.bat` again. `output\index.html` opens.
4. For each task, give `TASK.md` to your AI (paste it into the chat or, if it is an
   agent with file access, ask it to do the task) and save the answer as
   `RESULT.md` in the same folder.
5. Double-click again: review `CHANGES.html` and paste `FOR-CONFLUENCE.html`
   into Confluence.

Running it again is safe: it never touches your input folders and never
overwrites a `RESULT.md`.

## With an installed agent: Claude Code, Codex, Gemini or Copilot (recommended)

If one of these tools is installed and signed in, the workshop asks it for the
`RESULT.md` files that are missing, one task at a time:

```
amanuense.bat --ai-cli copilot      (or claude, codex, gemini)
```

or, so you do not have to type it every time, in the `.env` in the repo root:
`AMANUENSE_AI_CLI=copilot`.

- Each task goes in through standard input and the agent works in an empty
  temporary folder: it cannot see your folders, only the task.
- If a task fails (quota, expired session), the index says so and the others carry on.
- Use the tool and account that your organization allows for these documents.

With a large model, the result follows the rules much more closely than with a small
local model; the "data without a source" warning works the same with all of them.

## With a local AI (optional)

If you have Ollama or LM Studio, the workshop asks it for the missing `RESULT.md`
files itself. In the `.env` in the repo root:

```
AMANUENSE_AI_URL=http://localhost:11434/v1
AMANUENSE_AI_MODEL=qwen3-coder
```

`AMANUENSE_AI_KEY` is only needed for an API that requires a key. Always use an AI that
your organization allows for these documents.

## Change log: what changed and who did it

Each run updates `output/log.html` (linked from the index). To use it,
download the latest Word file, replace the one in `1-confluence-export/` and
run the workshop. The log records:

- **Confluence**: each page that changed since the previous export, with the lines
  added and removed. If you set up the API, it also shows who changed it, when, and
  the version comment. The first time, it only saves the reference.
- **Code**: the commits of the repos you list in `repos.txt`, with their author and branch.
  A line is a local clone (left as it is) or a URL, which is cloned into `repos/` and fetched on
  every run. Add `@ develop, feature/x` to follow those branches or `@ *` for all of them; without
  it, only the checked-out branch counts. If a new commit touches a file or a repo that a page
  mentions, the log asks you to review that page and prepares its task in `output/code/`, with the
  commits and their diff, so the AI can propose the updated text. Same process as the other tasks.
  With an AI configured, the workshop first triages each of those tasks into `TRIAJE.json`.
  It only writes a proposal for the ones the commits really make wrong (`actualizar`), and
  skips `ruido`: commits that change nothing the page says. `dudosa` is left for the page's
  author to decide. If the same page already has a request proposal, the code changes are
  applied on top of it (`encadenar`), so the delivery ends up with a single page.

  ```
  C:\code\hmi-tracks @ develop
  https://bitbucket.example.com/scm/team/hmi-base.git @ *
  ```
- **On a schedule**: `scripts\schedule-windows.ps1` runs the workshop every day at 08:00
  (`-At 07:30`, `-Every weekly`, `-Remove`; anything after `--` is passed on, such as
  `-- --ai-cli copilot`). It never opens the browser and never asks for a password, so save the
  Bitbucket credentials in Git first (one manual `git clone` does it). On Linux, a cron line:
  `0 8 * * * /path/to/amanuense.sh --no-open`.
- **Requests**: write a line "- Name: what to change" in `requests.md`. The
  configured AI answers which page to touch, what to change and why, and
  leaves its task in `output/requests/`. The same process applies there as with
  the other tasks: `RESULT.md`, `CHANGES.html` and `FOR-CONFLUENCE.html`.
- **Long pages**: above 40,000 characters the AI does not rewrite the page. It answers with
  `SEARCH/REPLACE` blocks, and the workshop applies only the ones whose text appears exactly once.
  The others become a `> PENDING: edit not applied` line, so nothing is lost silently.
- **Workshop**: each proposal that becomes ready, with the user who ran the workshop.
  To set that name, use `AMANUENSE_USER`.

To see who changed each page, create a personal token in Confluence (your
avatar → Settings → Personal Access Tokens) and add this to the `.env` in the
repo root:

```
AMANUENSE_CONFLUENCE_URL=https://your-confluence
AMANUENSE_CONFLUENCE_TOKEN=your-token
AMANUENSE_CONFLUENCE_SPACE=SPACE_KEY
```

The token stays on your computer and is only used to read the version history.
On Confluence Cloud, also add `AMANUENSE_CONFLUENCE_USER=your-email`. If there is no
network, the log keeps working without authors and says so in its warnings.

## Hand it over

```
amanuense.bat deliver --zip
./amanuense.sh deliver --zip
```

It gathers every ready proposal into `output/delivery-DATE/`:
- `pages/` and `new/`: one folder per page, holding `CHANGES.html`, `FOR-CONFLUENCE.html` and
  `RESULT.md`. When several proposals touch the same page, the chained one wins.
- `README.md`: lists each page and where it came from (a request with its author, the code
  review or the local documentation), the pages left for their author to decide, and every
  PENDING / CONFLICT note.
- The capability radiator, if it was generated.
- With `--zip`, a zip of the whole folder.

`CHANGES.html` opens with those notes, so the reviewer sees what is missing first.

## Move MIND to Obsidian

The same "Export to Word" from MIND (the Confluence of the Atlassian suite) can be
turned into an Obsidian vault, so you can read and link the documentation offline:

```
amanuense.bat obsidian "Documents\docs-workshop\1-confluence-export\MIND.docx" "Documents\MyVault\MIND"
./amanuense.sh obsidian ~/docs-workshop/1-confluence-export/MIND.docx ~/MyVault/MIND
```

- Each root page (H1) becomes a folder with an `_index.md`; each child (H2) becomes a note;
  if the child has grandchildren (H3), it becomes a folder with its own `_index.md` and one note per grandchild.
- Images go to `_media/` and are inserted as `![[image.png]]`; each index
  links to its children with `[[path|title]]`.
- It does not overwrite existing notes: if an export is already in that folder, repeat with `--force`
  (notes you edited by hand inside that folder are rewritten).
- Optional: `assets/obsidian/letravora.css` is the theme from the video. Copy it to
  the vault's `.obsidian/snippets/` and turn it on in Settings → Appearance → CSS snippets.

## Comparison by content (optional)

With [obsidian-search](https://github.com/gitsual/obsidian-search) installed in the same
Python, `amanuense.bat --content` also detects
renamed pages and duplicates by content, and `--content
--contradictions` looks for sentences that contradict each other.

## The Brick documentation repo

`src/amanuense/skeleton/en/` is a skeleton for the team's shared repo: common documentation,
brick documentation, agents and skills. To copy it into a new repo: `amanuense agents PATH` writes the native
files for each tool; the rest is copied as is. The skills are the same workshop rules,
written so that any agent (Claude Code, Copilot, a Teams bot)
can follow them. Start with [`skeleton/en/README.md`](../src/amanuense/skeleton/en/README.md) and the
guide [agents or skills](../src/amanuense/skeleton/en/docs/common/agents-or-skills.md).
