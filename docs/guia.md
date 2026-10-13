# amanuense: guía del taller de documentación

Reescribe y actualiza páginas de Confluence a partir de dos fuentes:
el último «Export to Word» de la sección y tu carpeta local de trabajo.
Todo se ejecuta en tu equipo; no sube nada a ningún sitio.

## Qué hace

1. Compara el export con tu carpeta y escribe un **informe**: qué páginas hay que
   actualizar, cuáles son nuevas, qué está duplicado, qué choca y qué páginas de
   Confluence no tienen equivalente local (candidatas a borrar o a fusionar).
2. Prepara una **tarea por página** (`TAREA.md`) con todo lo que una IA necesita:
   reglas, instrucciones de actualización, página actual, plantilla y Biblia.
3. Cuando guardas la respuesta de la IA como `RESULTADO.md`, genera
   `CAMBIOS.html` (qué cambia, para que lo apruebes) y `PARA-CONFLUENCE.html`
   (abrir → seleccionar todo → copiar → pegar en Confluence).
4. Marca los **datos sin fuente**: cifras, versiones, siglas, nombres o
   identificadores del resultado que no aparecen en nada de lo que recibió la IA.
   Salen arriba de `CAMBIOS.html` y en el índice. No dependen de la IA que uses:
   son lo primero que hay que comprobar antes de aprobar.

La plantilla de páginas nuevas se pasa a la IA vacía (títulos y etiquetas), para
que los valores del ejemplo de la plantilla no acaben en la página nueva.

## Probarlo en cinco minutos (Windows)

Sólo hace falta Python 3 (python.org, marcando «Add to PATH»).

1. Doble clic en **`amanuense.bat`** (en la raíz del repo). La primera vez crea
   `Documentos\taller-docs` y abre la carpeta.
2. Rellena las carpetas:
   - `1-export-confluence\`: el Word exportado (menú «···» de la página →
     Exportar → Exportar a Word → «Esta página y sus hijos»).
   - `2-mi-documentacion\`: tu carpeta (.docx, .md o .txt). Lo que sustituye a una
     página lleva **su mismo título** y un párrafo que empieza por
     `Instrucciones de actualización:`. Lo nuevo no lo lleva; si una página nueva
     debe seguir la plantilla (una capacidad, por ejemplo), añade la línea
     `Plantilla: sí`.
   - `3-biblia\`: lo que manda sobre todo lo demás (arquitectura de referencia,
     requisitos de publicación en Nexus, estándares de repos). Un documento con
     «plantilla» en el nombre pasa a ser la plantilla de las páginas nuevas.
3. Doble clic otra vez en `amanuense.bat`. Se abre `salida\index.html`.
4. Para cada tarea, da `TAREA.md` a tu IA (pegarlo en el chat o, si es un agente
   con acceso a ficheros, pedirle que la haga) y guarda la respuesta como
   `RESULTADO.md` en la misma carpeta.
5. Doble clic otra vez: revisa `CAMBIOS.html` y pega `PARA-CONFLUENCE.html` en
   Confluence.

Volver a ejecutar es seguro: nunca toca tus carpetas de entrada ni pisa un
`RESULTADO.md`.

## Con un agente instalado: Claude Code, Codex, Gemini o Copilot (recomendado)

Si tienes instalada y con sesión iniciada una de estas herramientas, el taller le
pide los `RESULTADO.md` que falten, una tarea cada vez:

```
amanuense.bat --ai-cli copilot      (o claude, codex, gemini)
```

o, para no escribirlo cada vez, en el `.env` de la raíz del repo:
`AMANUENSE_AI_CLI=copilot`.

- Cada tarea viaja por la entrada estándar y el agente trabaja en una carpeta
  temporal vacía: no ve tus carpetas, sólo la tarea.
- Si una tarea falla (cuota, sesión caducada), el índice lo dice y las demás siguen.
- Usa la herramienta y la cuenta que tu organización permita para estos documentos.

Con un modelo grande el resultado se ciñe mucho más a las reglas que con un modelo
local pequeño; el aviso de «datos sin fuente» funciona igual con todos.

## Con una IA local (opcional)

Si tienes Ollama o LM Studio, el taller pide él mismo los `RESULTADO.md` que falten.
En el `.env` de la raíz del repo:

```
AMANUENSE_AI_URL=http://localhost:11434/v1
AMANUENSE_AI_MODEL=qwen3-coder
```

`AMANUENSE_AI_KEY` sólo hace falta para una API con clave. Usa siempre una IA que
tu organización permita para estos documentos.

## Registro de cambios: qué cambió y quién

Cada ejecución actualiza `salida/registro.html` (enlazado desde el índice). Para
usarlo, descarga el Word más reciente, sustituye el de `1-export-confluence/` y
ejecuta el taller. El registro anota:

- **Confluence**: cada página que cambió desde el export anterior, con las líneas
  añadidas y quitadas. Si configuras la API, también quién la cambió, cuándo y
  el comentario de versión. La primera vez sólo guarda la referencia.
- **Código**: los commits de los clones locales de Bitbucket que listes en
  `repos.txt` (una ruta por línea), con su autor. Si un commit toca un fichero o
  un repo que cita una página, el registro pide revisarla.
- **Peticiones**: escribe en `peticiones.md` una línea «- Nombre: qué hay que
  cambiar». La IA configurada responde qué página tocar, qué cambiar y por qué,
  y deja su tarea en `salida/peticiones/`. Allí se sigue el mismo proceso que con
  las demás tareas: `RESULTADO.md`, `CAMBIOS.html` y `PARA-CONFLUENCE.html`.
- **Taller**: cada propuesta que queda lista, con el usuario que ejecutó el taller.
  Para fijar ese nombre, usa `AMANUENSE_USER`.

Para ver quién cambió cada página, crea un token personal en Confluence (tu
avatar → Configuración → Tokens de acceso personal) y añade en el `.env` de la
raíz del repo:

```
AMANUENSE_CONFLUENCE_URL=https://tu-confluence
AMANUENSE_CONFLUENCE_TOKEN=tu-token
AMANUENSE_CONFLUENCE_SPACE=CLAVE_DEL_ESPACIO
```

El token se queda en tu equipo y sólo se usa para leer el historial de versiones.
En Confluence Cloud, añade también `AMANUENSE_CONFLUENCE_USER=tu-correo`. Si no hay
red, el registro sigue funcionando sin autores y lo indica en sus avisos.

## Comparación por contenido (opcional)

Con [obsidian-search](https://github.com/gitsual/obsidian-search) instalado en el mismo
Python, `amanuense.bat --content` detecta
también páginas renombradas y duplicados por contenido, y `--content
--contradictions` busca frases que se contradicen.

## El repo de documentación del Brick

`src/amanuense/skeleton/` es un esqueleto para el repo común del equipo: documentación común,
documentación del brick, agentes y skills. Para copiarlo en un repo nuevo: `amanuense agents RUTA` escribe los ficheros
nativos de cada herramienta; el resto se copia tal cual. Las skills son las mismas reglas del
taller escritas para que cualquier agente (Claude Code, Copilot, un bot de Teams)
las siga. Empieza por [`skeleton/README.md`](../src/amanuense/skeleton/README.md) y por la guía
[agentes o skills](../src/amanuense/skeleton/docs/comun/agentes-o-skills.md).
