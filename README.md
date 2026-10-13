<div align="center">

<h1>amanuense</h1>

<p>
<em>An <strong>amanuense</strong> is the scribe who takes dictation and copies it out clean.<br>
They do not decide what the text says. They keep it straight, and they note who said what.</em><br>
<strong>This is that scribe for a team's Confluence: it compares the published pages with your drafts and your code,<br>prepares one AI-ready task per page, and keeps a log of what changed and who changed it.</strong>
</p>

<p>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-1F2A30?style=for-the-badge&logo=python&logoColor=D9C7A3">
  <img alt="stdlib only" src="https://img.shields.io/badge/core-zero%20deps-1F2A30?style=for-the-badge&labelColor=1F2A30&color=B08D57">
  <img alt="53 tests" src="https://img.shields.io/badge/53%20tests-linux%20%2B%20windows-1F2A30?style=for-the-badge&labelColor=1F2A30&color=6E7F5C">
  <img alt="four agent CLIs" src="https://img.shields.io/badge/claude%20·%20codex%20·%20gemini%20·%20copilot-1F2A30?style=for-the-badge&labelColor=1F2A30&color=D9C7A3">
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-1F2A30?style=for-the-badge&labelColor=1F2A30&color=8C3B2E">
</p>

<a href="#-install"><strong>Install</strong></a> ·
<a href="#-the-workshop"><strong>The workshop</strong></a> ·
<a href="#-who-changed-what"><strong>Who changed what</strong></a> ·
<a href="#-ask-for-a-change"><strong>Ask for a change</strong></a> ·
<a href="#-pick-your-ai"><strong>Pick your AI</strong></a> ·
<a href="#-the-team-repo"><strong>The team repo</strong></a> ·
<a href="#-companion-obsidian-search"><strong>Companion</strong></a> ·
<a href="#-why-this-exists"><strong>Why</strong></a> ·
<a href="#-status"><strong>Status</strong></a>

</div>

---

## ⬇ Install

It needs Python 3.11 and nothing else. There is no setup step and no dependency.

```sh
git clone git@github.com:gitsual/amanuense.git
cd amanuense
./amanuense.sh          # first run creates ~/taller-docs and tells you what to drop in it
```

> [!NOTE]
> The workshop speaks Spanish: folders, reports and the AI prompts. The step-by-step
> user guide is [docs/guia.md](docs/guia.md).

<details>
<summary><strong>Windows 11</strong></summary>

Install [Python](https://www.python.org/downloads/windows/) and tick *Add python.exe to PATH*.
Then double-click `amanuense.bat`. The first run creates `Documents\taller-docs` and opens it.
Every later double-click analyses the folder and opens `salida\index.html`.

</details>

<details>
<summary><strong>As a package</strong></summary>

```sh
pip install -e .        # gives you the `amanuense` command
amanuense init ~/taller-docs
amanuense run ~/taller-docs --ai-cli claude
```

</details>

## 📝 The workshop

```
taller-docs/
  1-export-confluence/   the Word export of the section (page + children)
  2-mi-documentacion/    your drafts: new pages, and old ones with «Instrucciones de actualización»
  3-biblia/              what overrides everything: reference architecture, standards
  peticiones.md          change requests, one line each
  repos.txt              local clones of the code repos
  salida/                report, one task folder per page, the change log
```

Each run:

1. Compares the export with your drafts and writes a report. It lists what to update, what is new,
   what is duplicated and which Confluence pages have no local counterpart.
2. Writes a `TAREA.md` per page. The file carries the rules, the instructions, the current page,
   the template skeleton and the bible. You can give it to any AI.
3. Turns every `RESULTADO.md` it finds into two pages. `PARA-CONFLUENCE.html` is ready to copy and
   paste. `CAMBIOS.html` is the diff you approve.
4. Flags **data without a source**: figures, versions, acronyms or names in the result that appear
   nowhere in what the AI was given.

It never writes into the input folders and never overwrites a `RESULTADO.md`.

## 👥 Who changed what

To update, download the newest Word export and drop it in place of the old one. `salida/registro.html` then
records four kinds of change:

| Source | What | Who |
| --- | --- | --- |
| Confluence | lines added and removed per page since the previous export | author, date and version comment from the REST API |
| Code | commits in the clones listed in `repos.txt`, and the pages that mention the touched files | the commit author |
| Requests | the page the AI picked, what to change and why | whoever wrote the request |
| Workshop | proposals ready for review | whoever ran the workshop |

The Word export carries no authors, so the "who" for Confluence comes from the API. To enable it,
put a personal access token in a local `.env`:

```
AMANUENSE_CONFLUENCE_URL=https://your-confluence
AMANUENSE_CONFLUENCE_TOKEN=...
AMANUENSE_CONFLUENCE_SPACE=SPACEKEY
```

Data Center uses the token as a Bearer token on `/rest/api`. Cloud also needs
`AMANUENSE_CONFLUENCE_USER` and uses `/wiki/rest/api`. Without a token the log still records what
changed, but not who changed it.

## ✋ Ask for a change

Add a line to `peticiones.md`:

```
- Ana: the deployment port is now 8443
```

On the next run, the AI reads the request and the list of pages. It answers which page to change,
what to change and why, and the workshop prepares that page's task under `salida/peticiones/`.
If the AI names no valid page, the request is retried on the next run.

## 🤖 Pick your AI

| Flag | Engine |
| --- | --- |
| `--ai-cli claude` | Claude Code (`claude -p`) |
| `--ai-cli codex` | Codex (`codex exec`, read-only sandbox) |
| `--ai-cli gemini` | Gemini CLI |
| `--ai-cli copilot` | GitHub Copilot CLI |
| `--ai-url URL --ai-model M` | any OpenAI-compatible API (Ollama, LM Studio, vLLM) |

The prompt always goes to the engine on stdin, and each call runs in an empty temporary folder.
With no AI configured, you paste each `TAREA.md` into a chat yourself.

## 🗂 The team repo

`src/amanuense/skeleton/` is a starting point for the team's documentation repo. It holds the
bible, the shared docs, one agent and three skills. Write the skills and agents once, then run
`amanuense agents PATH` to generate the native files for each tool: `.claude/`, `.agents/`,
`.codex/`, `.gemini/` and `.github/agents/`.

## 🔗 Companion: obsidian-search

[obsidian-search](https://github.com/gitsual/obsidian-search) is a local semantic search engine.
When both are installed in the same Python, `--content` uses its embeddings to match renamed pages
and duplicated content, and `--contradictions` uses its NLI judge to find sentences that contradict
each other. Without it, everything else works.

## 💡 Why this exists

| | Confluence alone | A chat with the AI | amanuense |
| --- | --- | --- | --- |
| Drafts vs published pages | by hand | paste both, every time | report on every run |
| Who changed a page | page history, one page at a time | no | log across all pages |
| Code changes that outdate a page | no | no | flagged per commit |
| Invented data | n/a | you have to spot it | flagged before you approve |
| Your documents leave the machine | n/a | yes | only to the AI you choose |

## 📍 Status

- **Tested:** the whole suite on Linux and on Windows 11. On Windows that includes a double-click
  run and a request routed through a local Ollama. Claude Code and Codex were run live as
  engines on Linux.
- **Not tested yet:** the Confluence API against a real server. It is covered by a fake that
  answers like Data Center. Gemini CLI and Copilot CLI have not been tested live.
- The Confluence API only answers from inside your organisation's network. The log runs fine
  without it.

## License

MIT
