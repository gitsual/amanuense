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
        "delivery": "delivery", "pages_dir": "pages", "new_dir": "new", "readme": "README.md",
        "live": "confluence-live.json", "intake_ignore": "intake-ignore.txt",
    },
    "es": {
        "export": "1-export-confluence", "local": "2-mi-documentacion", "bible": "3-biblia", "out": "salida",
        "guide": "LEEME.md", "requests": "peticiones.md", "requests_dir": "peticiones", "repos": "repos.txt",
        "report": "informe.md", "log_html": "registro.html", "log_json": "registro.json",
        "snapshot": "registro-export.json", "tasks": "tareas", "task": "TAREA.md", "result": "RESULTADO.md",
        "paste": "PARA-CONFLUENCE.html", "changes": "CAMBIOS.html", "current": "ACTUAL.md",
        "local_copy": "LOCAL.md", "verb_update": "actualizar", "verb_new": "nueva", "workspace": "taller-docs",
        "code_dir": "codigo", "repos_dir": "repos",
        "delivery": "entrega", "pages_dir": "paginas", "new_dir": "nuevas", "readme": "LEEME.md",
        "live": "confluence-en-vivo.json", "intake_ignore": "ignorar-al-cargar.txt",
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
    "task_material_intro": {
        "en": "Act as a technical writer. Update the current page with the new material below: add what is "
              "new, correct what it shows is out of date, and keep everything else as it is. Material that "
              "does not belong on this page is left out.",
        "es": "Actúa como redactor técnico. Actualiza la página actual con el material nuevo de abajo: añade lo "
              "que sea nuevo, corrige lo que demuestre que está desactualizado y conserva todo lo demás. El "
              "material que no corresponda a esta página se deja fuera.",
    },
    "task_material": {"en": "## New material ({rels})", "es": "## Material nuevo ({rels})"},
    "task_material_from": {"en": "### From `{rel}`", "es": "### De `{rel}`"},
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
    "notices_n": {"en": "{n} notes", "es": "{n} avisos"},
    "notices_none": {"en": "No PENDING or CONFLICT.", "es": "Sin PENDIENTE ni CONFLICTO."},
    "notice_marker": {"en": r"(PENDING|CONFLICT)", "es": r"(PENDIENTE|CONFLICTO)"},
    "edit_failed": {"en": "> PENDING: edit not applied ({why}): {search}",
                    "es": "> PENDIENTE: edición no aplicada ({why}): {search}"},
    "edit_missing": {"en": "text not found", "es": "texto no encontrado"},
    "edit_ambiguous": {"en": "text appears {n} times", "es": "el texto aparece {n} veces"},
    "edits_mode": {
        "en": "## How to answer (this page is long)\n\n"
              "Do NOT return the whole page. Return only edit blocks, one per change:\n\n"
              "<<<<<<< SEARCH\nexact lines copied from the current page (unique; avoid headings)\n=======\n"
              "the new lines\n>>>>>>> REPLACE\n\n"
              "After the blocks, write the `## Change log` section; it is added at the end of the page.",
        "es": "## Cómo responder (esta página es larga)\n\n"
              "NO devuelvas la página entera. Devuelve solo bloques de edición, uno por cambio:\n\n"
              "<<<<<<< SEARCH\nlíneas exactas copiadas de la página actual (únicas; evita los encabezados)\n=======\n"
              "las líneas nuevas\n>>>>>>> REPLACE\n\n"
              "Tras los bloques, escribe la sección `## Registro de cambios`; se añade al final de la página.",
    },
    "deliver_title": {"en": "# Delivery, {date}", "es": "# Entrega, {date}"},
    "deliver_pages": {"en": "## Pages to update (`{dir}/`)", "es": "## Páginas que actualizar (`{dir}/`)"},
    "deliver_new": {"en": "## New pages (`{dir}/`)", "es": "## Páginas nuevas (`{dir}/`)"},
    "deliver_files": {
        "en": "Each folder: `{changes}` (the diff, with its notes first), `{paste}` (select all and paste "
              "into the page) and `{result}` (the page in Markdown).",
        "es": "Cada carpeta: `{changes}` (el diff, con sus avisos al principio), `{paste}` (seleccionar todo "
              "y pegar en la página) y `{result}` (la página en Markdown).",
    },
    "deliver_from_request": {"en": "request from {by}", "es": "petición de {by}"},
    "deliver_from_code": {"en": "code review", "es": "revisión del código"},
    "deliver_from_docs": {"en": "local documentation", "es": "documentación local"},
    "deliver_notes": {"en": "{n} notes", "es": "{n} avisos"},
    "deliver_note": {"en": "1 note", "es": "1 aviso"},
    "deliver_doubtful": {
        "en": "## For the page author to decide\n\nCommits touch these pages, but only their author knows "
              "whether they must change:",
        "es": "## Para que decida el autor de la página\n\nHay commits que tocan estas páginas, pero solo su "
              "autor sabe si deben cambiar:",
    },
    "deliver_notices": {"en": "## Notes to resolve", "es": "## Avisos por resolver"},
    "deliver_radiator": {"en": "## Capability radiator (`radiador/`)", "es": "## Radiador de capacidades (`radiador/`)"},
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
    # ── Confluence storage read as Markdown: what has no Markdown form stays visible ──
    # ── documents dropped into the review app ──
    "intake_bad_path": {"en": "The path «{path}» is not allowed (it could leave its folder).",
                        "es": "La ruta «{path}» no está permitida (podría salirse de su carpeta)."},
    "intake_bad_batch": {"en": "That upload is not open any more: add the files again.",
                         "es": "Esa carga ya no está abierta: vuelve a añadir los ficheros."},
    "intake_unsupported": {"en": "«{path}» is not a document amanuense can read.",
                           "es": "«{path}» no es un documento que amanuense sepa leer."},
    "intake_file_too_big": {"en": "«{path}» is bigger than {mb} MB.", "es": "«{path}» supera los {mb} MB."},
    "intake_batch_too_big": {"en": "The upload would go over {mb} MB: send it in parts.",
                             "es": "La carga superaría los {mb} MB: envíala por partes."},
    "intake_incomplete": {"en": "«{path}» arrived incomplete: try again.", "es": "«{path}» ha llegado incompleto: inténtalo otra vez."},
    "intake_hash_mismatch": {"en": "«{path}» arrived damaged (its fingerprint does not match): try again.",
                             "es": "«{path}» ha llegado dañado (su huella no coincide): inténtalo otra vez."},
    "intake_unknown_file": {"en": "«{rel}» is not an uploaded file of this workshop.",
                            "es": "«{rel}» no es un fichero cargado en este taller."},
    "intake_ignore_text": {
        "en": "# Files to leave out when documentation is added in the review app.\n"
              "# One pattern per line, like .gitignore: «name/» is any folder of that name, a pattern with «/»\n"
              "# matches the path, any other the file name; «!pattern» brings files back. Built in already:\n"
              "# logs, lockfiles, test results, build output, node_modules, .git and temporary files.\n"
              "#   old-drafts/\n#   *-backup.md\n",
        "es": "# Ficheros que dejar fuera al añadir documentación desde la app de revisión.\n"
              "# Un patrón por línea, como .gitignore: «nombre/» es cualquier carpeta con ese nombre, un patrón\n"
              "# con «/» se compara con la ruta y el resto con el nombre; «!patrón» los recupera. Ya incluidos:\n"
              "# logs, ficheros de bloqueo, resultados de tests, salidas de compilación, node_modules, .git y temporales.\n"
              "#   borradores-viejos/\n#   *-copia.md\n",
    },
    "storage_macro": {"en": "⟦Confluence macro: {name}{params}⟧", "es": "⟦Macro de Confluence: {name}{params}⟧"},
    "storage_image": {"en": "⟦Confluence image: {name}⟧", "es": "⟦Imagen de Confluence: {name}⟧"},
    "storage_attachment": {"en": "⟦Confluence attachment: {name}⟧", "es": "⟦Adjunto de Confluence: {name}⟧"},
    "storage_link": {"en": "⟦link to the page «{name}»⟧", "es": "⟦enlace a la página «{name}»⟧"},
    "storage_user": {"en": "⟦Confluence user: {name}⟧", "es": "⟦Usuario de Confluence: {name}⟧"},
    "storage_layout": {"en": "⟦Confluence column layout⟧", "es": "⟦Diseño en columnas de Confluence⟧"},
    "storage_tasks": {"en": "⟦Confluence task list⟧", "es": "⟦Lista de tareas de Confluence⟧"},
    "storage_element": {"en": "⟦Confluence element: {name}⟧", "es": "⟦Elemento de Confluence: {name}⟧"},
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
    # ── review ──
    "conflict_word": {"en": "CONFLICT", "es": "CONFLICTO"},
    "review_unknown": {"en": "No proposal is ready in {rel}.", "es": "No hay ninguna propuesta lista en {rel}."},
    "review_open_conflicts": {
        "en": "Decide the open CONFLICT notes first ({n}). The first one: {first}",
        "es": "Decide primero los CONFLICTO abiertos ({n}). El primero: {first}"},
    "review_publish_unapproved": {"en": "Approve the page before publishing it.",
                                  "es": "Aprueba la página antes de publicarla."},
    "review_notice_gone": {"en": "That notice is no longer in the text (it was edited). Reload the page.",
                           "es": "Ese aviso ya no está en el texto (se ha editado). Recarga la página."},
    "review_approved": {"en": "approved", "es": "aprobada"},
    "review_discarded": {"en": "discarded: {reason}", "es": "descartada: {reason}"},
    "review_reopened": {"en": "back to review", "es": "vuelta a revisión"},
    "review_edited": {"en": "text edited", "es": "texto editado"},
    "review_decided": {"en": "decided «{notice}»: {decision}", "es": "decidido «{notice}»: {decision}"},
    "review_reworked": {"en": "rewritten by the AI: {instruction}", "es": "reescrita por la IA: {instruction}"},
    "review_published_api": {"en": "published in Confluence: {url}", "es": "publicada en MIND: {url}"},
    "review_published_manual": {"en": "pasted into Confluence by hand: {url}",
                                "es": "pegada a mano en MIND: {url}"},
    "review_promoted": {"en": "sent to be written despite the triage",
                        "es": "enviada a redactar pese al triaje"},
    "review_promoted_reason": {"en": "{by} asked to review it (triage said: {before})",
                               "es": "{by} pidió revisarla (el triaje decía: {before})"},
    "rework_prompt": {
        "en": "{task}\n\n## Current proposal\n\n{proposal}\n\n## What the reviewer asks\n\n{instruction}\n\n"
              "Reply with the whole page, applying what the reviewer asks to the current proposal.",
        "es": "{task}\n\n## Propuesta actual\n\n{proposal}\n\n## Lo que pide quien revisa\n\n{instruction}\n\n"
              "Responde con la página entera, aplicando a la propuesta actual lo que pide quien revisa."},
    # ── publishing to Confluence ──
    "mind_https_only": {"en": "The Confluence address must start with https:// (the token must not travel in clear).",
                        "es": "La dirección de MIND tiene que empezar por https:// (el token no puede viajar en claro)."},
    "mind_unreachable": {"en": "Cannot reach {base} ({reason}). Are you on the company network or VPN?",
                         "es": "No se llega a {base} ({reason}). ¿Estás en la red de la empresa o con la VPN?"},
    "mind_not_json": {"en": "Confluence answered something that is not JSON (a login page?). Check the address.",
                      "es": "MIND ha respondido algo que no es JSON (¿una página de inicio de sesión?). Revisa la dirección."},
    "mind_redirected": {"en": "Confluence redirects to another site (single sign-on?). The token is not sent there.",
                        "es": "MIND redirige a otro sitio (¿inicio de sesión único?). El token no se envía ahí."},
    "mind_400": {"en": "Confluence rejected the content: {detail}", "es": "MIND ha rechazado el contenido: {detail}"},
    "mind_401": {"en": "Confluence does not accept the token: check it is copied whole and has not expired.",
                 "es": "MIND no acepta el token: revisa que esté bien copiado y que no haya caducado."},
    "mind_403": {"en": "Your user has no permission for that page or space.",
                 "es": "Tu usuario no tiene permiso para esa página o ese espacio."},
    "mind_404": {"en": "The page does not exist in Confluence (renamed or deleted?).",
                 "es": "La página no existe en MIND (¿la han renombrado o borrado?)."},
    "mind_409": {"en": "Someone else saved the page meanwhile. Check it again before publishing.",
                 "es": "Otra persona ha guardado la página mientras tanto. Vuelve a comprobarla antes de publicar."},
    "mind_413": {"en": "The page is too big for Confluence.", "es": "La página es demasiado grande para MIND."},
    "mind_429": {"en": "Confluence asks to wait a little. Try again in a minute.",
                 "es": "MIND pide que espere un poco. Prueba de nuevo en un minuto."},
    "mind_root_missing": {"en": "The page «{title}» is not in the space {space}: check the root page in Settings.",
                          "es": "La página «{title}» no está en el espacio {space}: revisa la página raíz en Ajustes."},
    "space_offline_cache": {"en": "Confluence could not be read ({error}); using the copy fetched on {when}.",
                            "es": "No se ha podido leer Confluence ({error}); se usa la copia leída el {when}."},
    "space_offline_export": {"en": "Confluence could not be read ({error}); using the Word export instead.",
                             "es": "No se ha podido leer Confluence ({error}); se usa el export de Word."},
    "space_cut": {"en": "The space has more than {n} pages: only the first {n} were read. Set a root page in Settings.",
                  "es": "El espacio tiene más de {n} páginas: solo se han leído las {n} primeras. Indica una página raíz en Ajustes."},
    "mind_5xx": {"en": "Confluence is not answering well right now (error {code}). Try later.",
                 "es": "MIND no responde bien ahora mismo (error {code}). Prueba más tarde."},
    "mind_title_taken": {"en": "A page called «{title}» already exists: {url}",
                         "es": "Ya existe una página llamada «{title}»: {url}"},
    "mind_pick_parent": {"en": "Choose the page it goes under.", "es": "Elige la página de la que cuelga."},
    "mind_parent_missing": {"en": "There is no page «{title}» in space {space}.",
                            "es": "No hay ninguna página «{title}» en el espacio {space}."},
    "mind_page_missing": {"en": "There is no page «{title}» in space {space} (renamed?).",
                          "es": "No hay ninguna página «{title}» en el espacio {space} (¿la han renombrado?)."},
    "mind_no_export_date": {"en": "The export has no date, so a later edit in Confluence cannot be ruled out. Export again.",
                            "es": "El export no tiene fecha y no se puede descartar un cambio posterior en MIND. Vuelve a exportar."},
    "mind_changed_after_export": {
        "en": "{by} changed the page on {when}, after the export ({exported}). Export again so that edit is not lost.",
        "es": "{by} cambió la página el {when}, después del export ({exported}). Vuelve a exportar para no perder ese cambio."},
    "mind_would_lose": {"en": "The page holds things the proposal cannot carry and would be lost: {items}. "
                              "Edit those sections by hand in Confluence.",
                        "es": "La página tiene elementos que la propuesta no lleva y se perderían: {items}. "
                              "Edita esas secciones a mano en MIND."},
    "mind_would_convert": {"en": "These become plain: {items}.", "es": "Esto pasa a formato simple: {items}."},
    "mind_accept_warnings": {"en": "Accept the warnings first: {items}", "es": "Acepta primero los avisos: {items}"},
    "mind_el_macro": {"en": "macro «{name}»", "es": "macro «{name}»"},
    "mind_el_attachment": {"en": "attachment «{name}»", "es": "adjunto «{name}»"},
    "mind_el_image": {"en": "image", "es": "imagen"},
    "mind_el_link": {"en": "internal links", "es": "enlaces internos"},
    "mind_el_emoticon": {"en": "emoticons", "es": "emoticonos"},
    "mind_el_layout": {"en": "column layout", "es": "diseño en columnas"},
    "mind_version_message": {"en": "amanuense: reviewed by {by}", "es": "amanuense: revisada por {by}"},
    "mind_undo_message": {"en": "amanuense: undone by {by}", "es": "amanuense: deshecha por {by}"},
    "mind_not_verified": {"en": "Confluence answered, but reading the page back does not show the change. Check it by hand.",
                          "es": "MIND ha respondido, pero al releer la página no se ve el cambio. Revísala a mano."},
    "mind_nothing_to_undo": {"en": "This page was not published from here.",
                             "es": "Esta página no se publicó desde aquí."},
    "mind_undo_new_page": {"en": "A page created from here is deleted by hand in Confluence: {url}",
                           "es": "Una página creada desde aquí se borra a mano en MIND: {url}"},
    "mind_undone": {"en": "publication undone: {url}", "es": "publicación deshecha: {url}"},
    # ── review app ──
    "ui_title": {"en": 'amanuense — review', "es": 'amanuense — revisión'},
    "ui_console": {"en": 'amanuense is open in your browser: {url}\nKeep this window open while you work; close it (or use «Close amanuense») to stop.', "es": 'amanuense está abierto en el navegador: {url}\nDeja esta ventana abierta mientras trabajas; ciérrala (o usa «Cerrar amanuense») para terminar.'},
    "ui_server_gone": {"en": 'amanuense is not running any more. Start it again from its launcher.', "es": 'amanuense ya no está en marcha. Vuelve a abrirlo desde su lanzador.'},
    "ui_missing": {"en": 'Missing: {fields}', "es": 'Falta: {fields}'},
    "ui_mind_not_configured": {"en": 'Confluence is not configured: open Settings and add its address, space and token.', "es": 'MIND no está configurado: abre Ajustes y añade la dirección, el espacio y el token.'},
    "ui_ai_not_configured": {"en": 'No AI is configured: choose one in Settings.', "es": 'No hay ninguna IA configurada: elige una en Ajustes.'},
    "ui_nothing_to_open": {"en": 'There is nothing to open yet.', "es": 'Todavía no hay nada que abrir.'},
    "ui_too_big": {"en": 'The text is too big to send.', "es": 'El texto es demasiado grande para enviarlo.'},
    "ui_busy": {"en": 'Wait until the current task finishes.', "es": 'Espera a que termine la tarea en curso.'},
    "ui_you_are": {"en": 'You are {user}', "es": 'Eres {user}'},
    "ui_run": {"en": 'Look for changes', "es": 'Buscar cambios'},
    "ui_run_help": {"en": 'Reads the Confluence export, your drafts, the requests and the repos, and prepares the proposals', "es": 'Lee el export de MIND, los borradores, las peticiones y los repos, y prepara las propuestas'},
    "ui_settings": {"en": 'Settings', "es": 'Ajustes'},
    "ui_more": {"en": 'More ▾', "es": 'Más ▾'},
    "ui_radiator": {"en": 'Build the capability radiator', "es": 'Generar el radiador de capacidades'},
    "ui_deliver": {"en": 'Prepare the delivery (zip)', "es": 'Preparar la entrega (zip)'},
    "ui_open_log": {"en": 'Open the change log', "es": 'Abrir el registro de cambios'},
    "ui_open_workspace": {"en": 'Open the workshop folder', "es": 'Abrir la carpeta del taller'},
    "ui_close": {"en": 'Close amanuense', "es": 'Cerrar amanuense'},
    "ui_closed": {"en": 'amanuense is closed', "es": 'amanuense se ha cerrado'},
    "ui_closed_help": {"en": 'You can close this tab. To come back, start amanuense again.', "es": 'Ya puedes cerrar esta pestaña. Para volver, abre amanuense otra vez.'},
    "ui_job_run": {"en": 'Looking for changes…', "es": 'Buscando cambios…'},
    "ui_job_radiator": {"en": 'Building the radiator…', "es": 'Generando el radiador…'},
    "ui_job_deliver": {"en": 'Preparing the delivery…', "es": 'Preparando la entrega…'},
    "ui_job_rework": {"en": 'The AI is rewriting the page…', "es": 'La IA está reescribiendo la página…'},
    "ui_job_failed": {"en": 'It did not finish: {error}', "es": 'No ha terminado: {error}'},
    "ui_job_ok": {"en": 'Done.', "es": 'Hecho.'},
    "ui_run_done": {"en": '{ready} of {tasks} pages have a proposal.', "es": '{ready} de {tasks} páginas tienen propuesta.'},
    "ui_run_warnings": {"en": 'Warnings from the search', "es": 'Avisos de la búsqueda'},
    "ui_deliver_done": {"en": 'Delivery ready', "es": 'Entrega preparada'},
    "ui_radiator_done": {"en": 'Radiator ready', "es": 'Radiador generado'},
    "ui_open_folder": {"en": 'Open the folder', "es": 'Abrir la carpeta'},
    "ui_open_radiator": {"en": 'Open the radiator', "es": 'Abrir el radiador'},
    "ui_empty_title": {"en": 'Nothing to review yet', "es": 'Todavía no hay nada que revisar'},
    "ui_empty_1": {"en": 'Put the Word export of the Confluence pages in «1-…export» (page menu ··· → Export → Word → this page and its children).', "es": 'Pon el export de Word de las páginas de MIND en «1-export-confluence» (menú ··· de la página → Exportar → Word → esta página y sus hijos).'},
    "ui_empty_2": {"en": 'Add your drafts, the requests (peticiones.md) and the repos to watch (repos.txt) if you have them.', "es": 'Añade, si los tienes, tus borradores, las peticiones (peticiones.md) y los repos que vigilar (repos.txt).'},
    "ui_empty_3": {"en": 'Press «Look for changes». Every proposed page appears here to review.', "es": 'Pulsa «Buscar cambios». Cada página propuesta aparecerá aquí para revisarla.'},
    "ui_pick": {"en": 'Choose a page on the left.', "es": 'Elige una página a la izquierda.'},
    "ui_progress": {"en": '{done} of {total} pages closed', "es": '{done} de {total} páginas cerradas'},
    "ui_search": {"en": 'Search a page', "es": 'Buscar una página'},
    "ui_filter_todo": {"en": 'All', "es": 'Todas'},
    "ui_filter_pendiente": {"en": 'To review', "es": 'Por revisar'},
    "ui_filter_conflicto": {"en": 'With conflicts', "es": 'Con conflictos'},
    "ui_filter_aprobada": {"en": 'Approved', "es": 'Aprobadas'},
    "ui_filter_publicada": {"en": 'Published', "es": 'Publicadas'},
    "ui_filter_descartada": {"en": 'Discarded', "es": 'Descartadas'},
    "ui_none_here": {"en": 'No pages here.', "es": 'No hay páginas aquí.'},
    "ui_new_page": {"en": 'new', "es": 'nueva'},
    "ui_n_conflicts": {"en": '{n} conflict(s)', "es": '{n} conflicto(s)'},
    "ui_n_pending": {"en": '{n} pending', "es": '{n} pendiente(s)'},
    "ui_stale": {"en": 'Confluence changed', "es": 'MIND cambió'},
    "ui_stale_help": {"en": 'The page changed in the last export after you approved it. Look at the changes again before publishing.', "es": 'La página cambió en el último export después de aprobarla. Repasa los cambios antes de publicar.'},
    "ui_set_aside": {"en": 'Set aside by the triage ({n})', "es": 'Apartadas por el triaje ({n})'},
    "ui_set_aside_help": {"en": 'Commits the AI judged harmless for the documentation (noise) or that only their author can judge (doubtful). If one does matter, send it to be written.', "es": 'Commits que la IA juzgó inofensivos para la documentación (ruido) o que solo puede valorar su autor (dudosa). Si alguno sí importa, mándalo a redactar.'},
    "ui_cat_ruido": {"en": 'noise', "es": 'ruido'},
    "ui_cat_dudosa": {"en": 'doubtful', "es": 'dudosa'},
    "ui_cat_actualizar": {"en": 'update', "es": 'actualizar'},
    "ui_cat_encadenar": {"en": 'on top of a request', "es": 'sobre una petición'},
    "ui_promote": {"en": 'Write it anyway', "es": 'Redactar igualmente'},
    "ui_promoted": {"en": 'Sent. Press «Look for changes» to write it.', "es": 'Enviada. Pulsa «Buscar cambios» para redactarla.'},
    "status_pendiente": {"en": 'To review', "es": 'Por revisar'},
    "status_aprobada": {"en": 'Approved', "es": 'Aprobada'},
    "status_publicada": {"en": 'Published', "es": 'Publicada'},
    "status_descartada": {"en": 'Discarded', "es": 'Descartada'},
    "origin_request": {"en": 'Request from {by}', "es": 'Petición de {by}'},
    "origin_chained": {"en": 'Request from {by} + code ({repos})', "es": 'Petición de {by} + código ({repos})'},
    "origin_code": {"en": 'Code review: {repos}', "es": 'Revisión del código: {repos}'},
    "origin_docs": {"en": 'Your drafts', "es": 'Tus borradores'},
    "ui_n_repos": {"en": '{n} repositories', "es": '{n} repositorios'},
    "ui_edited_by_hand": {"en": 'edited by hand', "es": 'editada a mano'},
    "ui_discarded_note": {"en": 'Discarded by {by}: {note}', "es": 'Descartada por {by}: {note}'},
    "ui_published_api": {"en": 'Published in Confluence by {by} on {when} (version {version}).', "es": 'Publicada en MIND por {by} el {when} (versión {version}).'},
    "ui_published_manual": {"en": 'Pasted into Confluence by {by} on {when}.', "es": 'Pegada en MIND por {by} el {when}.'},
    "ui_open_in_mind": {"en": 'Open in Confluence ↗', "es": 'Abrir en MIND ↗'},
    "ui_undo": {"en": 'Undo the publication', "es": 'Deshacer la publicación'},
    "ui_undo_help": {"en": 'The page goes back to how it was before publishing, as a new version. Nothing is deleted: Confluence keeps every version.', "es": 'La página vuelve a como estaba antes de publicar, como versión nueva. No se borra nada: MIND guarda todas las versiones.'},
    "ui_undone": {"en": 'Publication undone.', "es": 'Publicación deshecha.'},
    "ui_no_notices": {"en": '✓ No PENDING or CONFLICT in this page.', "es": '✓ Esta página no tiene PENDIENTE ni CONFLICTO.'},
    "ui_notices": {"en": 'Notes to look at ({n})', "es": 'Avisos que revisar ({n})'},
    "ui_conflict": {"en": 'CONFLICT', "es": 'CONFLICTO'},
    "ui_pending": {"en": 'PENDING', "es": 'PENDIENTE'},
    "ui_jump": {"en": 'Show in the text', "es": 'Ver en el texto'},
    "ui_decide": {"en": 'Decide', "es": 'Decidir'},
    "ui_resolve": {"en": 'Resolve', "es": 'Resolver'},
    "ui_decision_ph": {"en": 'What goes in the page instead of this note', "es": 'Qué va en la página en lugar de este aviso'},
    "ui_decision_help": {"en": 'Your text replaces the note line in the page. You can retouch it later in «Edit».', "es": 'Tu texto sustituye la línea del aviso en la página. Luego puedes retocarlo en «Editar».'},
    "ui_save_decision": {"en": 'Save the decision', "es": 'Guardar la decisión'},
    "ui_decided": {"en": 'Decision saved.', "es": 'Decisión guardada.'},
    "ui_rework_about": {"en": 'About «{notice}»:', "es": 'Sobre «{notice}»:'},
    "ui_ask_ai": {"en": 'Ask the AI to rewrite it', "es": 'Pedir a la IA que la reescriba'},
    "ui_ai_ph": {"en": 'What to change, e.g. «shorten the installation section»', "es": 'Qué cambiar, por ejemplo «acorta la sección de instalación»'},
    "ui_ai_help": {"en": 'The AI gets the original task, the page as it is now and your instruction. Your current text is kept as the base.', "es": 'La IA recibe la tarea original, la página tal como está ahora y tu instrucción. Tu texto actual es la base.'},
    "ui_cancel": {"en": 'Cancel', "es": 'Cancelar'},
    "ui_tab_changes": {"en": 'Changes', "es": 'Cambios'},
    "ui_tab_preview": {"en": 'How it will look', "es": 'Cómo quedará'},
    "ui_tab_edit": {"en": 'Edit', "es": 'Editar'},
    "ui_tab_origin": {"en": 'Why', "es": 'Por qué'},
    "ui_tab_history": {"en": 'History ({n})', "es": 'Historial ({n})'},
    "ui_new_page_help": {"en": 'A new page: there is nothing to compare with. This is how it will look:', "es": 'Página nueva: no hay nada con qué compararla. Así quedará:'},
    "ui_no_changes": {"en": 'The proposal does not change the page.', "es": 'La propuesta no cambia la página.'},
    "ui_diff_help": {"en": '{n} changed blocks. Left: Confluence today. Right: the proposal. Red is removed, green is added.', "es": '{n} bloques cambiados. Izquierda: MIND hoy. Derecha: la propuesta. En rojo lo que sale, en verde lo que entra.'},
    "ui_before": {"en": 'Confluence today', "es": 'MIND hoy'},
    "ui_after": {"en": 'Proposal', "es": 'Propuesta'},
    "ui_show_equal": {"en": 'Show {n} unchanged lines', "es": 'Mostrar {n} líneas sin cambios'},
    "ui_edit_help": {"en": 'Markdown on the left, the result on the right. Saving puts the page back to review.', "es": 'Markdown a la izquierda, el resultado a la derecha. Al guardar, la página vuelve a «Por revisar».'},
    "ui_save": {"en": 'Save', "es": 'Guardar'},
    "ui_saved": {"en": 'Saved.', "es": 'Guardado.'},
    "ui_discard_edits": {"en": 'Undo my edits', "es": 'Deshacer mis cambios'},
    "ui_requests": {"en": 'What was asked', "es": 'Qué se pidió'},
    "ui_what": {"en": 'Change:', "es": 'Cambio:'},
    "ui_triage": {"en": 'Why the AI rewrote it', "es": 'Por qué la IA la reescribió'},
    "ui_commits": {"en": 'Commits that touch this page ({n})', "es": 'Commits que tocan esta página ({n})'},
    "ui_others": {"en": '{n} other proposal(s) for this page were merged into this one.', "es": 'Otras {n} propuesta(s) para esta página se han unido en esta.'},
    "ui_origin_docs": {"en": 'It comes from your drafts in «2-…» with update instructions.', "es": 'Sale de tus borradores de «2-mi-documentacion» con instrucciones de actualización.'},
    "ui_show_task": {"en": 'See exactly what the AI was given', "es": 'Ver exactamente lo que recibió la IA'},
    "ui_task_title": {"en": 'The task given to the AI', "es": 'La tarea que recibió la IA'},
    "ui_no_history": {"en": 'Nobody has reviewed this page yet.', "es": 'Nadie ha revisado esta página todavía.'},
    "ui_discard": {"en": 'Discard', "es": 'Descartar'},
    "ui_discard_ph": {"en": 'Why (it is kept in the log)', "es": 'Por qué (queda en el registro)'},
    "ui_discard_help": {"en": 'The page is left out of publishing and of the delivery. You can bring it back later.', "es": 'La página queda fuera de la publicación y de la entrega. Puedes recuperarla después.'},
    "ui_discarded": {"en": 'Discarded.', "es": 'Descartada.'},
    "ui_reopen": {"en": 'Back to review', "es": 'Volver a revisar'},
    "ui_reopened": {"en": 'Back to review.', "es": 'Vuelve a «Por revisar».'},
    "ui_approve": {"en": 'Approve', "es": 'Aprobar'},
    "ui_approved": {"en": 'Approved. Now you can publish it.', "es": 'Aprobada. Ya puedes publicarla.'},
    "ui_approve_blocked": {"en": 'Decide the conflicts before approving.', "es": 'Decide los conflictos antes de aprobar.'},
    "ui_publish": {"en": 'Publish in Confluence…', "es": 'Publicar en MIND…'},
    "ui_next": {"en": 'Next ›', "es": 'Siguiente ›'},
    "ui_publish_title": {"en": 'Publish «{title}»', "es": 'Publicar «{title}»'},
    "ui_pub_api": {"en": 'Automatic', "es": 'Automático'},
    "ui_pub_manual": {"en": 'By hand', "es": 'A mano'},
    "ui_pub_api_off": {"en": 'To publish automatically, add the Confluence address, space and your personal token in Settings. Meanwhile, use «By hand».', "es": 'Para publicar automáticamente, añade en Ajustes la dirección de MIND, el espacio y tu token personal. Mientras tanto, usa «A mano».'},
    "ui_parent": {"en": 'Goes under the page', "es": 'Cuelga de la página'},
    "ui_parent_ph": {"en": 'Title of the parent page', "es": 'Título de la página padre'},
    "ui_parent_help": {"en": 'Choose the page it goes under; then it is checked.', "es": 'Elige de qué página cuelga; después se comprueba.'},
    "ui_checking": {"en": 'Checking the page in Confluence…', "es": 'Comprobando la página en MIND…'},
    "ui_found_page": {"en": 'Found in Confluence: version {version}, last saved by {by} on {when}.', "es": 'Encontrada en MIND: versión {version}, guardada por última vez por {by} el {when}.'},
    "ui_found_parent": {"en": 'Parent page found: {title}.', "es": 'Página padre encontrada: {title}.'},
    "ui_blocked": {"en": 'It cannot be published automatically:', "es": 'No se puede publicar automáticamente:'},
    "ui_blocked_help": {"en": 'Use «By hand» to paste only the sections that change, or fix the cause and check again.', "es": 'Usa «A mano» para pegar solo las secciones que cambian, o corrige la causa y vuelve a comprobar.'},
    "ui_no_blockers": {"en": 'Nothing would be lost and nobody edited it after the export.', "es": 'No se pierde nada y nadie la ha editado después del export.'},
    "ui_accept_warnings": {"en": 'I understand and want to publish', "es": 'Lo entiendo y quiero publicar'},
    "ui_pub_api_safety": {"en": 'Before saving, the current page is copied to «mind-copias» and can be undone from here. Confluence also keeps every version.', "es": 'Antes de guardar, la página actual se copia en «mind-copias» y se puede deshacer desde aquí. MIND además guarda todas las versiones.'},
    "ui_publish_now": {"en": 'Publish now', "es": 'Publicar ahora'},
    "ui_publishing": {"en": 'Publishing…', "es": 'Publicando…'},
    "ui_published_ok": {"en": 'Published and checked in Confluence.', "es": 'Publicada y comprobada en MIND.'},
    "ui_check_again": {"en": 'Check again', "es": 'Volver a comprobar'},
    "ui_step_open": {"en": 'Open the page in Confluence and press «Edit».', "es": 'Abre la página en MIND y pulsa «Editar».'},
    "ui_step_open_new": {"en": 'Open the parent page in Confluence and create a child page with this title.', "es": 'Abre en MIND la página padre y crea una página hija con este título.'},
    "ui_no_mind_url": {"en": '(add the Confluence address in Settings to get a link here)', "es": '(añade la dirección de MIND en Ajustes para tener aquí el enlace)'},
    "ui_step_copy": {"en": 'Copy the page, already formatted:', "es": 'Copia la página, ya con formato:'},
    "ui_copy": {"en": 'Copy page', "es": 'Copiar página'},
    "ui_copied": {"en": '✓ Copied', "es": '✓ Copiada'},
    "ui_copy_failed": {"en": 'The browser did not let it copy: use «How it will look», select all and copy.', "es": 'El navegador no ha dejado copiar: usa «Cómo quedará», selecciona todo y copia.'},
    "ui_step_paste": {"en": 'In the Confluence editor, select all the old content (if the page has images or macros, only the sections that change), paste and press «Publish».', "es": 'En el editor de MIND, selecciona todo el contenido viejo (si la página tiene imágenes o macros, solo las secciones que cambian), pega y pulsa «Publicar».'},
    "ui_step_done": {"en": 'When it is saved in Confluence, mark it here:', "es": 'Cuando esté guardada en MIND, márcala aquí:'},
    "ui_page_url": {"en": 'Address of the page', "es": 'Dirección de la página'},
    "ui_mark_published": {"en": 'It is published', "es": 'Ya está publicada'},
    "ui_marked": {"en": 'Marked as published.', "es": 'Marcada como publicada.'},
    "ui_mind": {"en": 'Confluence (MIND)', "es": 'MIND (Confluence)'},
    "ui_mind_help": {"en": 'Only needed to publish automatically. Without it everything else works, and publishing is done by hand.', "es": 'Solo hace falta para publicar automáticamente. Sin esto funciona todo lo demás y se publica a mano.'},
    "ui_mind_url": {"en": 'Address', "es": 'Dirección'},
    "ui_mind_space": {"en": 'Space key', "es": 'Clave del espacio'},
    "ui_mind_token": {"en": 'Personal access token', "es": 'Token personal'},
    "ui_token_ph": {"en": 'Paste it here', "es": 'Pégalo aquí'},
    "ui_token_saved": {"en": 'Saved ✓ (paste another to replace it)', "es": 'Guardado ✓ (pega otro para cambiarlo)'},
    "ui_token_help": {"en": 'In Confluence: your avatar → Settings → Personal Access Tokens → Create token. It is stored encrypted for your Windows user, outside the workshop, and is never shown again.', "es": 'En MIND: tu avatar → Configuración → Tokens de acceso personal → Crear token. Se guarda cifrado para tu usuario de Windows, fuera del taller, y no se vuelve a mostrar.'},
    "ui_mind_user": {"en": 'E-mail (Atlassian Cloud only)', "es": 'Correo (solo Atlassian Cloud)'},
    "ui_mind_user_ph": {"en": 'Leave empty for Data Center', "es": 'Déjalo vacío en Data Center'},
    "ui_test": {"en": 'Test the connection', "es": 'Probar la conexión'},
    "ui_testing": {"en": 'Testing…', "es": 'Probando…'},
    "ui_test_ok": {"en": '✓ Connected as {user}.', "es": '✓ Conectado como {user}.'},
    "ui_forget_token": {"en": 'Forget the token', "es": 'Olvidar el token'},
    "ui_token_forgotten": {"en": 'Token forgotten.', "es": 'Token olvidado.'},
    "ui_ai": {"en": 'AI', "es": 'IA'},
    "ui_ai_settings_help": {"en": 'Used to look for changes and to rewrite a page on request. An installed agent CLI, or an OpenAI-compatible address.', "es": 'Se usa al buscar cambios y para reescribir una página cuando lo pides. Un agente instalado (CLI) o una dirección compatible con OpenAI.'},
    "ui_ai_cli": {"en": 'Installed agent', "es": 'Agente instalado'},
    "ui_ai_none": {"en": 'None', "es": 'Ninguno'},
    "ui_ai_url": {"en": 'Or an OpenAI-compatible address', "es": 'O una dirección compatible con OpenAI'},
    "ui_ai_model": {"en": 'Model', "es": 'Modelo'},
    "ui_from_env": {"en": 'These come from environment variables and win over what you save here: {fields}', "es": 'Estos vienen de variables de entorno y mandan sobre lo que guardes aquí: {fields}'},
    "cli_review": {"en": "open the review app: see every change, decide, edit and publish",
                   "es": "abrir la app de revisión: ver todos los cambios, decidir, editar y publicar"},
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
    "triage_prompt": {
        "en": "You review whether commits make a documentation page wrong. Page: «{title}»:\n\n{page}\n\n"
              "Commits and their diffs:\n\n{commits}\n\n"
              "Reply ONLY with a JSON object: "
              '{{"categoria": "actualizar" if the page states something these commits make wrong, '
              '"ruido" if they change nothing the page says, "dudosa" if only the page author can decide; '
              '"motivo": "one sentence", "cambios": ["one concrete change per item, naming the section"]}}',
        "es": "Revisas si unos commits dejan mal una página de documentación. Página: «{title}»:\n\n"
              "{page}\n\nCommits y sus diffs:\n\n{commits}\n\n"
              "Responde SOLO con un objeto JSON: "
              '{{"categoria": "actualizar" si la página afirma algo que estos commits dejan mal, '
              '"ruido" si no cambian nada de lo que dice la página, "dudosa" si solo puede decidirlo su autor; '
              '"motivo": "una frase", "cambios": ["un cambio concreto por elemento, nombrando la sección"]}}',
    },
    "code_triaged": {
        "en": "# {title}\n\nUpdate instructions: the code changed what this page describes ({reason}). "
              "Apply ONLY these changes and keep everything else:\n\n{changes}\n",
        "es": "# {title}\n\nInstrucciones de actualización: el código cambió lo que describe esta página ({reason}). "
              "Aplica SOLO estos cambios y conserva todo lo demás:\n\n{changes}\n",
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
    "code_commit_line": {"en": "- {repo} · {branch} · {sha} · {by}: {subject}",
                         "es": "- {repo} · {branch} · {sha} · {by}: {subject}"},
    "code_older": {"en": "## {n} older commits (no diff: read them in the repo if the page needs it)",
                   "es": "## {n} commits anteriores (sin diff: consultarlos en el repo si la página lo necesita)"},
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
    "cli_deliver": {"en": "gather the ready pages into output/delivery-DATE with a README",
                    "es": "reúne las páginas listas en salida/entrega-FECHA con un LEEME"},
    "cli_zip": {"en": "also make a .zip of the delivery", "es": "crea además un .zip de la entrega"},
    "cli_radiator": {"en": "capability radiator from repos.txt, the export and radiador.json",
                     "es": "radiador de capacidades a partir de repos.txt, el export y radiador.json"},
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
