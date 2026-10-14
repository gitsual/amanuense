"""
i18n — the workshop's two languages: English (default) and Spanish.

Everything a person reads or a file is named after comes from here: workshop folder
and file names, the task given to the AI, the report, the log and the HTML pages.
Data stored in the log (entry kinds, change kinds) stays language-neutral; only its
labels are translated.

The language is chosen, in order, by an existing workshop's own folders (a Spanish
workshop stays Spanish), then by --lang / AMANUENSE_LANG, then English.
"""
from __future__ import annotations

import os
from pathlib import Path

LANGS = ("en", "es")
DEFAULT = "en"
_current = DEFAULT

NAMES: dict[str, dict[str, str]] = {
    "en": {
        "export": "1-confluence-export", "local": "2-my-docs", "bible": "3-bible", "out": "output",
        "guide": "GUIDE.md", "requests": "requests.md", "requests_dir": "requests", "repos": "repos.txt",
        "report": "report.md", "log_html": "log.html", "log_json": "log.json", "snapshot": "log-export.json",
        "tasks": "tasks", "task": "TASK.md", "result": "RESULT.md", "paste": "FOR-CONFLUENCE.html",
        "changes": "CHANGES.html", "current": "CURRENT.md", "local_copy": "LOCAL.md",
        "verb_update": "update", "verb_new": "new", "workspace": "docs-workshop",
        "code_dir": "code", "repos_dir": "repos",
    },
    "es": {
        "export": "1-export-confluence", "local": "2-mi-documentacion", "bible": "3-biblia", "out": "salida",
        "guide": "LEEME.md", "requests": "peticiones.md", "requests_dir": "peticiones", "repos": "repos.txt",
        "report": "informe.md", "log_html": "registro.html", "log_json": "registro.json",
        "snapshot": "registro-export.json", "tasks": "tareas", "task": "TAREA.md", "result": "RESULTADO.md",
        "paste": "PARA-CONFLUENCE.html", "changes": "CAMBIOS.html", "current": "ACTUAL.md",
        "local_copy": "LOCAL.md", "verb_update": "actualizar", "verb_new": "nueva", "workspace": "taller-docs",
        "code_dir": "codigo", "repos_dir": "repos",
    },
}

TEXT: dict[str, dict[str, str]] = {
    # ── workshop guide ──
    "guide_text": {
        "en": """# Documentation workshop

1. Copy into `1-confluence-export/` the Word export from Confluence
   (page menu "···" → Export → Export to Word → "This page and its children").
2. Copy into `2-my-docs/` your working folder. Each document that replaces a page
   has the same title and a paragraph that starts with "Update instructions:".
   New documents do not; if a new one must follow the template (a capability, for
   example), add a line "Template: yes".
3. Copy into `3-bible/` the documents that override everything else
   (reference architecture, publishing requirements, repo standards).
   A document here whose name or title contains "template" becomes the template
   for new pages; otherwise the export's own is used.
4. Run the workshop. It opens `output/index.html` with the report and one task per page.
5. In each task, give `TASK.md` to your AI and save its answer as `RESULT.md`
   in the same folder. Run the workshop again.
6. Review `CHANGES.html`, open `FOR-CONFLUENCE.html`, select all, copy and
   paste into the Confluence page.

Nothing leaves this computer unless you set up an AI with --ai-url.
""",
        "es": """# Taller de documentación

1. Copia en `1-export-confluence/` el Word exportado de Confluence
   (menú «···» de la página → Exportar → Exportar a Word → «Esta página y sus hijos»).
2. Copia en `2-mi-documentacion/` tu carpeta de trabajo. Cada documento que
   sustituye a una página lleva su mismo título y un párrafo que empieza por
   «Instrucciones de actualización:». Los documentos nuevos no lo llevan; si uno
   nuevo debe seguir la plantilla (por ejemplo, una capacidad), añade una línea
   «Plantilla: sí».
3. Copia en `3-biblia/` los documentos que mandan sobre todo lo demás
   (arquitectura de referencia, requisitos de publicación, estándares de repos).
   Si dejas aquí un documento cuyo nombre o título contenga «plantilla», será la
   plantilla de las páginas nuevas; si no, se usa la del export.
4. Ejecuta el taller. Se abre `salida/index.html` con el informe y una tarea por página.
5. En cada tarea, da `TAREA.md` a tu IA y guarda su respuesta como `RESULTADO.md`
   en la misma carpeta. Vuelve a ejecutar el taller.
6. Revisa `CAMBIOS.html`, abre `PARA-CONFLUENCE.html`, selecciona todo, copia y
   pega en la página de Confluence.

Nada sale de este equipo salvo que configures una IA con --ai-url.
""",
    },
    "requests_text": {
        "en": """# Change requests

One line per request: "- Name: what to change". When the workshop runs, the AI
says which page to touch, what to change and why, and prepares its task.

""",
        "es": """# Peticiones de cambio

Una línea por petición: «- Nombre: qué hay que cambiar». Al ejecutar el taller,
la IA dice qué página tocar, qué cambiar y por qué, y prepara su tarea.

""",
    },
    "repos_text": {
        "en": "# Code repos to watch, one per line: a local clone or a URL to clone.\n"
              "# A URL is cloned into repos/ and fetched on every run; a local clone is left as it is.\n"
              "# Add \"@ develop, feature/x\" to follow those branches, or \"@ *\" for all of them.\n"
              "#   C:\\code\\hmi-tracks\n"
              "#   https://bitbucket.example.com/scm/team/repo.git @ *\n"
              "# The log records their commits; every page a new commit touches gets a task.\n",
        "es": "# Repos de código que vigilar, uno por línea: un clon local o una URL que clonar.\n"
              "# Una URL se clona en repos/ y se actualiza en cada ejecución; un clon local no se toca.\n"
              "# Añade «@ develop, feature/x» para seguir esas ramas, o «@ *» para todas.\n"
              "#   C:\\code\\hmi-tracks\n"
              "#   https://bitbucket.example.com/scm/team/repo.git @ *\n"
              "# El registro anota sus commits; cada página que toque un commit nuevo recibe una tarea.\n",
    },
    # ── the task given to the AI ──
    "rules": {
        "en": """## Rules

1. Do not invent data: names, versions, URLs, dates or owners.
   Do not add content that is not in this task: only write up and order what is already here.
   If something is missing, leave a line `> PENDING: what is missing`.
{bible_rule}3. Consistent and lean: remove repetition; if a block already lives on another page,
   replace it with "See the page "Title"".
4. Format: Markdown, starting with `# {title}`; tables in Markdown; no HTML.
5. End with `## Change log`, one bullet per change.
6. Reply ONLY with the page.
""",
        "es": """## Reglas

1. No inventes datos: nombres, versiones, URL, fechas ni responsables.
   No añadas contenido que no esté en esta tarea: sólo redacta y ordena lo que ya hay.
   Si falta algo, deja una línea `> PENDIENTE: qué falta`.
{bible_rule}3. Coherente y reducida: quita repeticiones; si un bloque ya vive en otra página,
   sustitúyelo por «Ver la página «Título»».
4. Formato: Markdown, empezando por `# {title}`; tablas en Markdown; sin HTML.
5. Termina con `## Registro de cambios`, una viñeta por cambio.
6. Responde SOLO con la página.
""",
    },
    "bible_rule": {
        "en": "2. The bible rules. If something contradicts it, do not choose: leave a line\n"
              "   `> CONFLICT: what clashes with what` and keep the current text.\n",
        "es": "2. La Biblia manda. Si algo la contradice, no elijas tú: deja una línea\n"
              "   `> CONFLICTO: qué choca con qué` y conserva el texto actual.\n",
    },
    "no_bible_rule": {
        "en": "2. If two parts of this task contradict each other, do not choose: leave a line\n"
              "   `> CONFLICT: what clashes with what` and keep the current text.\n",
        "es": "2. Si dos partes de esta tarea se contradicen, no elijas tú: deja una línea\n"
              "   `> CONFLICTO: qué choca con qué` y conserva el texto actual.\n",
    },
    "cut": {"en": "[… cut]", "es": "[… recortado]"},
    "task_update_title": {"en": "# Task: update the Confluence page \"{title}\"",
                          "es": "# Tarea: actualizar la página «{title}» de Confluence"},
    "task_update_intro": {
        "en": "Act as a technical writer. Rewrite the current page applying ONLY what the update "
              "instructions ask for; everything they do not mention stays.",
        "es": "Actúa como redactor técnico. Reescribe la página actual aplicando SOLO lo que "
              "piden las instrucciones de actualización; lo que no mencionan se conserva.",
    },
    "task_update_instructions": {"en": "## Update instructions (`{rel}`)",
                                 "es": "## Instrucciones de actualización (`{rel}`)"},
    "task_current_page": {"en": "## Current page in Confluence", "es": "## Página actual en Confluence"},
    "task_new_title": {"en": "# Task: new page \"{title}\"", "es": "# Tarea: página nueva «{title}»"},
    "task_new_intro": {"en": "Act as a technical writer. Turn the draft into a Confluence page.",
                       "es": "Actúa como redactor técnico. Convierte el borrador en una página de Confluence."},
    "task_template": {"en": "## Template (\"{title}\")", "es": "## Plantilla («{title}»)"},
    "task_template_hint": {
        "en": "Use its sections and labels in the same order; \"…\" marks where content goes. "
              "Fill in only what the draft or the bible says and leave `> PENDING` everywhere else.",
        "es": "Usa sus secciones y etiquetas en el mismo orden; «…» marca dónde va contenido. "
              "Rellena sólo con lo que diga el borrador o la Biblia y deja `> PENDIENTE` en el resto.",
    },
    "task_draft": {"en": "## Local draft (`{rel}`)", "es": "## Borrador local (`{rel}`)"},
    "task_bible": {"en": "## Bible (references that rule)", "es": "## Biblia (referencias que mandan)"},
    "system_prompt": {"en": "You are a technical writer. Reply only with the page in Markdown.",
                      "es": "Eres un redactor técnico. Responde solo con la página en Markdown."},
    "gemini_nudge": {"en": "Follow the task above.", "es": "Sigue la tarea anterior."},
    # ── pages ──
    "confluence_today": {"en": "Confluence today", "es": "Confluence hoy"},
    "local_draft": {"en": "Local draft", "es": "Borrador local"},
    "proposal": {"en": "Proposal", "es": "Propuesta"},
    "unsourced_note": {
        "en": "<p><b>Data without a source</b> (it appears in nothing the AI was given; "
              "check it before approving): {terms}</p>",
        "es": "<p><b>Datos sin fuente</b> (no aparecen en nada de lo que se dio a la IA; "
              "compruébalos antes de aprobar): {terms}</p>",
    },
    "state_ready": {"en": "ready", "es": "listo"},
    "state_pending": {"en": "pending: {result} missing", "es": "pendiente: falta {result}"},
    "state_unsourced_1": {"en": " · check 1 unsourced item", "es": " · revisar 1 dato sin fuente"},
    "state_unsourced_n": {"en": " · check {n} unsourced items", "es": " · revisar {n} datos sin fuente"},
    "state_ai_failed": {"en": " · the AI failed: {error}", "es": " · falló la IA: {error}"},
    "state_big": {
        "en": " · large ({k}k characters): use a long-context AI or split the local document by subpage",
        "es": " · grande ({k}k caracteres): usa una IA de contexto largo o divide el documento local por subpáginas",
    },
    "workshop_title": {"en": "Documentation workshop", "es": "Taller de documentación"},
    "index_intro": {
        "en": "Export pages at heading level {level}. Full report: {report}. What changed and who: {log}.",
        "es": "Páginas del export al nivel de encabezado {level}. Informe completo: {report}. "
              "Qué cambió y quién: {log}.",
    },
    "index_tasks": {"en": "Tasks ({ready}/{total} ready)", "es": "Tareas ({ready}/{total} listas)"},
    "col_folder": {"en": "Folder", "es": "Carpeta"},
    "col_page": {"en": "Page", "es": "Página"},
    "col_state": {"en": "State", "es": "Estado"},
    "col_files": {"en": "Files", "es": "Ficheros"},
    # ── report ──
    "report_title": {"en": "# Confluence ↔ local documentation", "es": "# Confluence ↔ documentación local"},
    "untitled": {"en": "(untitled)", "es": "(sin título)"},
    "similar_title": {"en": "similar title", "es": "título parecido"},
    # ── log ──
    "log_title": {"en": "Change log", "es": "Registro de cambios"},
    "log_intro": {
        "en": "What changed and who changed it. To ask for a change, add a line \"- Name: what to change\" "
              "to <code>{requests}</code> and run the workshop again. <a href=\"index.html\">Back to the workshop</a>.",
        "es": "Qué cambió y quién lo cambió. Para pedir un cambio, añade una línea «- Nombre: qué cambiar» "
              "a <code>{requests}</code> y vuelve a ejecutar el taller. <a href=\"index.html\">Volver al taller</a>.",
    },
    "log_warnings": {"en": "Warnings:", "es": "Avisos:"},
    "col_date": {"en": "Date", "es": "Fecha"},
    "col_source": {"en": "Source", "es": "Origen"},
    "col_who": {"en": "Who", "es": "Quién"},
    "col_what": {"en": "What", "es": "Qué"},
    "kind_confluence": {"en": "Confluence", "es": "Confluence"},
    "kind_codigo": {"en": "Code", "es": "Código"},
    "kind_peticion": {"en": "Request", "es": "Petición"},
    "kind_taller": {"en": "Workshop", "es": "Taller"},
    "change_cambiada": {"en": "page changed", "es": "página cambiada"},
    "change_nueva": {"en": "page added", "es": "página nueva"},
    "change_eliminada": {"en": "page removed", "es": "página eliminada"},
    "more_lines": {"en": "(and {n} more lines)", "es": "(y {n} líneas más)"},
    "review": {"en": "Review:", "es": "Revisar:"},
    "no_page": {"en": "The AI found no page: assign it by hand.", "es": "La IA no encontró página: asígnala a mano."},
    "what": {"en": "What:", "es": "Qué:"},
    "quote": {"en": "“{text}”", "es": "«{text}»"},
    "why": {"en": "Why:", "es": "Por qué:"},
    "proposal_ready": {"en": "proposal ready for review", "es": "propuesta lista para revisar"},
    "route_prompt": {
        "en": "You curate the documentation. Someone asks for a change. Pick the page to change from "
              "this list (use its exact title) and reply ONLY with a JSON object:\n"
              '{{"page": "exact title, or empty if none fits", "change": "what to change", "reason": "why"}}\n\n'
              "## Request from {by}\n\n{text}\n\n## Pages\n\n{listing}\n",
        "es": "Eres el curador de la documentación. Una persona pide un cambio. Elige la página que hay "
              "que cambiar de esta lista (usa su título exacto) y responde SOLO con un objeto JSON:\n"
              '{{"pagina": "título exacto o vacío si ninguna encaja", "cambio": "qué hay que cambiar", '
              '"motivo": "por qué"}}\n\n'
              "## Petición de {by}\n\n{text}\n\n## Páginas\n\n{listing}\n",
    },
    "request_local": {
        "en": "# {title}\n\nUpdate instructions: {change}\n\nRequest from {by}: {request}\n\nReason: {reason}\n",
        "es": "# {title}\n\nInstrucciones de actualización: {change}\n\nPetición de {by}: {request}\n\nMotivo: {reason}\n",
    },
    "err_request": {"en": "AI (request from {by}): {error}", "es": "IA (petición de {by}): {error}"},
    "err_sync": {"en": "could not update {repo}: {error}", "es": "no se pudo actualizar {repo}: {error}"},
    "code_local": {
        "en": "# {title}\n\nUpdate instructions: Commits in the code touch what this page describes. "
              "Check the page against them and change only what they make wrong; keep everything else. "
              "If the page is still right, return it unchanged.\n\n{commits}\n",
        "es": "# {title}\n\nInstrucciones de actualización: Hay commits en el código que tocan lo que "
              "describe esta página. Contrasta la página con ellos y cambia solo lo que dejen mal; "
              "conserva todo lo demás. Si la página sigue siendo correcta, devuélvela sin cambios.\n\n{commits}\n",
    },
    "code_commit": {"en": "## {repo} · {branch} · {sha} · {by}\n\n{subject}\n\n```diff\n{diff}\n```\n",
                    "es": "## {repo} · {branch} · {sha} · {by}\n\n{subject}\n\n```diff\n{diff}\n```\n"},
    "err_git": {"en": "git log failed in {repo}: {error}", "es": "git log falló en {repo}: {error}"},
    # ── Obsidian ──
    "vault_title": {"en": "Confluence export", "es": "Export de Confluence"},
    "vault_source": {"en": "Source: `{name}`", "es": "Origen: `{name}`"},
    "vault_pages": {"en": "Pages", "es": "Páginas"},
    "vault_clash": {
        "en": "{n} notes already exist (e.g. {first}); use --force to rewrite them",
        "es": "{n} notas ya existen (p. ej. {first}); usa --force para reescribirlas",
    },
    # ── command line ──
    "cli_description": {"en": "amanuense — workshop to rewrite and update Confluence pages. Non-destructive.",
                        "es": "amanuense — taller para reescribir y actualizar páginas de Confluence. No destructivo."},
    "cli_lang": {"en": "language: en or es (default: the workshop's own, else AMANUENSE_LANG, else en)",
                 "es": "idioma: en o es (por defecto, el del taller; si no, AMANUENSE_LANG; si no, en)"},
    "cli_init": {"en": "create the workshop folders", "es": "crea las carpetas del taller"},
    "cli_agents": {"en": "write skills and agents for Claude Code, Codex, Gemini and Copilot",
                   "es": "escribe skills y agentes para Claude Code, Codex, Gemini y Copilot"},
    "cli_agents_dest": {"en": "root of the repo to write them into", "es": "raíz del repo donde dejarlos"},
    "cli_agents_src": {"en": "folder with skills/, agents/ and AGENTS.md",
                       "es": "carpeta con skills/, agentes/ y AGENTS.md"},
    "cli_obsidian": {"en": "turn a Confluence export into an Obsidian vault",
                     "es": "pasa un export de Confluence a un vault de Obsidian"},
    "cli_export": {"en": "the exported .docx", "es": "el .docx exportado"},
    "cli_vault": {"en": "vault folder to write the notes into", "es": "carpeta del vault donde dejar las notas"},
    "cli_force": {"en": "rewrite notes that already exist", "es": "reescribir notas que ya existen"},
    "cli_run": {"en": "analyse, prepare tasks and publish the results",
                "es": "analiza, prepara tareas y publica los RESULTADO.md"},
    "cli_ai_url": {"en": "OpenAI-compatible API, e.g. http://localhost:11434/v1",
                   "es": "API compatible con OpenAI, p. ej. http://localhost:11434/v1"},
    "cli_ai_cli": {"en": "use an installed agent: claude, codex, gemini or copilot",
                   "es": "usar un agente instalado: claude, codex, gemini o copilot"},
    "cli_content": {"en": "also compare by content (RAG)", "es": "comparar también por contenido (RAG)"},
    "cli_contradictions": {"en": "with --content, contradiction judge", "es": "con --content, juez de contradicciones"},
    "cli_no_open": {"en": "do not open the browser at the end", "es": "no abrir el navegador al terminar"},
    "cli_needs_model": {"en": "--ai-url needs --ai-model (or AMANUENSE_AI_MODEL)",
                        "es": "--ai-url necesita --ai-model (o AMANUENSE_AI_MODEL)"},
    "cli_vault_done": {"en": "{notes} notes and {media} images in {vault}",
                       "es": "{notes} notas y {media} imágenes en {vault}"},
    "cli_warning": {"en": "warning:", "es": "aviso:"},
    "cli_ready": {"en": "{ready}/{total} tasks ready", "es": "{ready}/{total} tareas listas"},
    "err_engine": {"en": "unknown engine: {engine} (use {engines})", "es": "motor desconocido: {engine} (usa {engines})"},
    "err_not_installed": {"en": "{engine} is not installed or not on the PATH",
                          "es": "{engine} no está instalado o no está en el PATH"},
    "err_exit": {"en": "{engine} exited with code {code}: {tail}", "es": "{engine} terminó con código {code}: {tail}"},
    "err_empty": {"en": "{engine} returned no text", "es": "{engine} no devolvió texto"},
}


def use(lang: str) -> str:
    """Switch the language for everything that follows; returns it."""
    global _current
    if lang not in LANGS:
        raise ValueError(f"unknown language: {lang} (use {', '.join(LANGS)})")
    _current = lang
    return lang


def current() -> str:
    return _current


def name(key: str) -> str:
    return NAMES[_current][key]


def t(key: str, **fields) -> str:
    text = TEXT[key][_current]
    return text.format(**fields) if fields else text


def detect(root: Path | None) -> str | None:
    """The language of an existing workshop, from its folders; None when there is none."""
    if root is None or not Path(root).is_dir():
        return None
    for lang in LANGS:
        n = NAMES[lang]
        if any((Path(root) / n[k]).exists() for k in ("export", "local", "bible", "out")):
            return lang
    return None


def choose(root: Path | None = None, lang: str | None = None, env=os.environ) -> str:
    """Pick and switch to the language: the workshop's own, then `lang`, then AMANUENSE_LANG, then English."""
    return use(detect(root) or lang or env.get("AMANUENSE_LANG") or DEFAULT)
