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

Sólo hace falta Python 3.11 o superior (python.org). Marcar «Add python.exe to PATH» ayuda, pero el
lanzador encuentra Python también sin él; algunos instaladores ni siquiera muestran esa casilla. Si una
carpeta de la ruta lleva corchetes, como `[HMI]`, escribe la ruta entre comillas en la terminal:
`cd "C:\code\[HMI] docs"`.

1. La primera vez, ejecuta **`amanuense.bat --lang es`** (en la raíz del repo): crea
   `Documentos\docs-workshop` con las carpetas en español y la abre. Sin `--lang es`, el
   taller sale en inglés. Un taller que ya tiene las carpetas en español sigue en español,
   y si existe `Documentos\taller-docs` se usa esa carpeta. Desde ahí basta el doble clic.
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
3. Doble clic otra vez en `amanuense.bat`. Se abre la **app de revisión** en el navegador.
   Pulsa **Buscar cambios**: compara el export con tus carpetas y prepara una tarea por página.
4. Para cada tarea, da `TAREA.md` a tu IA (pegarlo en el chat o, si es un agente
   con acceso a ficheros, pedirle que la haga) y guarda la respuesta como
   `RESULTADO.md` en la misma carpeta. Con un agente configurado (más abajo), la app lo hace sola.
5. De vuelta en la app, revisa cada página, apruébala y publícala (siguiente apartado).

Volver a ejecutar es seguro: nunca toca tus carpetas de entrada ni pisa un
`RESULTADO.md`.

## Revisar y publicar: la app

El doble clic en `amanuense.bat` (o `./amanuense.sh` sin argumentos) abre una pequeña app en el
navegador. Solo funciona en tu ordenador (`127.0.0.1`), no hay que instalar nada y funciona sin
conexión. `amanuense review <taller> [--no-open]` la arranca a mano.

- **Bandeja**: una fila por página con su origen (una petición y su autor, la revisión del código o
  tus borradores), sus avisos y su estado: *pendiente*, *aprobada*, *publicada* o *descartada*. La
  barra de arriba cuenta cuántas están cerradas. Debajo, plegadas, las tareas que el triaje apartó
  (`ruido`, `dudosa`) con su motivo; **Redactar igualmente** manda una a la IA.
- **Una página** tiene cinco pestañas:
  - **Cambios**: la página actual y la propuesta lado a lado, bloque a bloque.
  - **Cómo quedará**: la página final.
  - **Editar**: el Markdown con vista previa en vivo. La versión de la IA se guarda en `RESULTADO.ia.md`.
  - **Por qué**: la petición o los commits que la originaron, con el motivo del triaje.
  - **Historial**: qué cambió en MIND y quién (con token).
- **Avisos**: cada PENDIENTE y CONFLICTO aparece encima de las pestañas. **Decidir** sustituye la
  línea del CONFLICTO por tu texto. No se puede aprobar una página con un CONFLICTO abierto.
- **Aprobar**, **Descartar** (con motivo) y **Siguiente**. Si MIND cambia después de aprobar una
  página, vuelve a *pendiente*.
- **Buscar cambios** está en la barra superior; el menú **Más** genera el radiador de capacidades,
  prepara el zip de la entrega y abre el registro de cambios.

Cada acción queda en `salida/registro.html` con tu nombre (`AMANUENSE_USER`, o el que pongas en la app).

### Publicar

**A mano (funciona siempre):** **Publicar en MIND… → A mano**. **Copiar página** pone la página
con formato en el portapapeles; **Abrir en MIND** te lleva a ella; pégala en el editor, guarda y
pulsa **Ya está publicada**. Copiar no marca nunca la página como publicada.

**Automático (opcional):** en **Ajustes**, escribe la dirección de MIND, la clave del espacio y un
token personal (tu avatar → Configuración → Tokens de acceso personal → Crear token) y pulsa
**Probar la conexión**. A partir de ahí, **Publicar ahora** actualiza la página por la API REST de
Confluence, con estas salvaguardas:

- **Bloquea** si la página cambió en MIND después de tu export, y dice quién la cambió y cuándo.
  Vuelve a exportar, o revísala a mano.
- **Bloquea** si la página tiene algo que el taller no sabe reconstruir (imágenes, adjuntos, macros
  de Jira, maquetación, menciones) y pasa al modo manual guiado, con la lista de lo que se perdería.
- Antes de cada actualización guarda la versión anterior en `salida/mind-copias/`; **Deshacer la
  publicación** la vuelve a subir como versión nueva.
- Después de publicar, vuelve a leer la página y solo la marca como *publicada* si la versión coincide.
- Las páginas nuevas necesitan una página padre que exista en el mismo espacio; si ya hay una página
  con ese título, se bloquea.

El token se guarda fuera del taller, cifrado para tu usuario de Windows
(`%APPDATA%\amanuense\settings.json`; en Linux, `~/.config/amanuense/` con permisos 600). Nunca
llega al navegador ni viaja en el zip de la entrega. **Antes del primer uso real, publica una sola
página de prueba en tu espacio personal.**

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
- **Código**: los commits de los repos que listes en `repos.txt`, con su autor y su rama. Cada
  línea es un clon local (no se toca) o una URL, que se clona en `repos/` y se actualiza en cada
  ejecución. Añade `@ develop, feature/x` para seguir esas ramas o `@ *` para todas; sin eso, solo
  cuenta la rama activa. Si un commit nuevo toca un fichero o un repo que cita una página, el
  registro pide revisarla y prepara su tarea en `salida/codigo/`, con los commits y su diff, para
  que la IA proponga el texto actualizado. El proceso es el mismo que con las demás tareas.
  Con una IA configurada, el taller hace primero un triaje de cada una de esas tareas y lo guarda
  en `TRIAJE.json`. Solo redacta propuesta para las que los commits dejan mal de verdad
  (`actualizar`). Descarta el `ruido`, es decir, los commits que no cambian nada de lo que dice la
  página, y deja las `dudosa` para que decida su autor. Si la misma página ya tiene una propuesta
  de petición, los cambios del código se aplican encima (`encadenar`) y en la entrega sale una
  sola página.

  ```
  C:\code\hmi-tracks @ develop
  https://bitbucket.example.com/scm/team/hmi-base.git @ *
  ```
- **Programado**: `scripts\schedule-windows.ps1` ejecuta el taller cada día a las 08:00
  (`-At 07:30`, `-Every weekly`, `-Remove`; lo que vaya tras `--` se pasa al taller, como
  `-- --ai-cli copilot`). Nunca abre el navegador ni pide contraseña, así que guarda antes las
  credenciales de Bitbucket en Git (basta un `git clone` a mano). En Linux, una línea de cron:
  `0 8 * * * /ruta/a/amanuense.sh --no-open`.
- **Peticiones**: escribe en `peticiones.md` una línea «- Nombre: qué hay que
  cambiar». La IA configurada responde qué página tocar, qué cambiar y por qué,
  y deja su tarea en `salida/peticiones/`. Allí se sigue el mismo proceso que con
  las demás tareas: `RESULTADO.md`, `CAMBIOS.html` y `PARA-CONFLUENCE.html`.
- **Páginas largas**: a partir de 40.000 caracteres, la IA no reescribe la página. Responde con
  bloques `SEARCH/REPLACE`, y el taller aplica solo los bloques cuyo texto aparece una única vez.
  Los demás quedan como una línea `> PENDIENTE: edición no aplicada`, así que nada se pierde en
  silencio.
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

## Configuración: qué se puede ajustar y dónde

Todo es opcional. Los **Ajustes** de la app guardan la dirección de Confluence, el space, el
usuario, el token y la IA en tu carpeta de usuario (`%APPDATA%\amanuense\settings.json` en
Windows, `~/.config/amanuense/` en el resto), nunca en el taller; en Windows el token va cifrado
con DPAPI. Una variable de entorno manda sobre los Ajustes. `run` (y por tanto una ejecución programada) solo lee
las variables de entorno, nunca los Ajustes.

| Variable | Qué | Ejemplo |
|---|---|---|
| `AMANUENSE_CONFLUENCE_URL` | Dirección base de Confluence | `https://confluence.example.com` |
| `AMANUENSE_CONFLUENCE_SPACE` | Clave del space de las páginas | `DOCS` |
| `AMANUENSE_CONFLUENCE_TOKEN` | Token personal (nunca lo subas al repo) | |
| `AMANUENSE_CONFLUENCE_USER` | Correo de la cuenta, solo para Confluence Cloud | `ana@example.com` |
| `AMANUENSE_AI_CLI` | Agente: `claude`, `codex`, `gemini`, `copilot` | `copilot` |
| `AMANUENSE_AI_URL`, `AMANUENSE_AI_MODEL`, `AMANUENSE_AI_KEY` | IA compatible con OpenAI en lugar de un agente | `http://localhost:11434/v1` |
| `AMANUENSE_USER` | Nombre que se anota en el registro | `ana.ruiz` |
| `AMANUENSE_LANG` | Idioma del taller: `en` o `es` | `es` |
| `AMANUENSE_CONFIG_DIR` | Otra carpeta para los Ajustes | |

Dentro del taller: `repos.txt` (repositorios y ramas que se siguen) y `radiador.json` (scope
npm y `registry`, la dirección de tu registro de paquetes).

## Entregar

```
amanuense.bat deliver --zip
./amanuense.sh deliver --zip
```

Reúne todas las propuestas listas en `salida/entrega-FECHA/`:
- `paginas/` y `nuevas/`: una carpeta por página con `CAMBIOS.html`, `PARA-CONFLUENCE.html` y
  `RESULTADO.md`. Si varias propuestas tocan la misma página, gana la encadenada.
- `LEEME.md`: cada página con su origen (petición de quién, revisión del código o
  documentación local), las páginas que debe decidir su autor y todos los PENDIENTE y CONFLICTO.
- El radiador de capacidades, si se ha generado.
- Con `--zip`, un zip de la carpeta.

`CAMBIOS.html` empieza con esos avisos, así quien revisa ve primero lo que falta.

## Pasar MIND a Obsidian

El mismo «Export to Word» de MIND (el Confluence de la suite Atlassian) se puede
convertir en un vault de Obsidian, para leer y enlazar la documentación sin red:

```
amanuense.bat obsidian "Documentos\docs-workshop\1-export-confluence\MIND.docx" "Documentos\MiVault\MIND"
./amanuense.sh obsidian ~/docs-workshop/1-export-confluence/MIND.docx ~/MiVault/MIND
```

- Cada página raíz (H1) es una carpeta con `_index.md`; cada hija (H2), una nota;
  si la hija tiene nietas (H3), pasa a carpeta con su `_index.md` y una nota por nieta.
- Las imágenes van a `_media/` y se insertan como `![[imagen.png]]`; cada índice
  enlaza a sus hijas con `[[ruta|título]]`.
- No pisa notas existentes: si ya hay un export en esa carpeta, repite con `--force`
  (las notas que hayas editado a mano dentro de esa carpeta se reescriben).
- Opcional: `assets/obsidian/letravora.css` es el tema del vídeo. Cópialo a
  `.obsidian/snippets/` del vault y actívalo en Ajustes → Apariencia → Fragmentos CSS.

## Comparación por contenido (opcional)

Con [obsidian-search](https://github.com/gitsual/obsidian-search) instalado en el mismo
Python, `amanuense.bat --content` detecta
también páginas renombradas y duplicados por contenido, y `--content
--contradictions` busca frases que se contradicen.

## El repo de documentación del Brick

`src/amanuense/skeleton/es/` es un esqueleto para el repo común del equipo: documentación común,
documentación del brick, agentes y skills. Para copiarlo en un repo nuevo: `amanuense agents RUTA` escribe los ficheros
nativos de cada herramienta; el resto se copia tal cual. Las skills son las mismas reglas del
taller escritas para que cualquier agente (Claude Code, Copilot, un bot de Teams)
las siga. Empieza por [`skeleton/es/README.md`](../src/amanuense/skeleton/es/README.md) y por la guía
[agentes o skills](../src/amanuense/skeleton/es/docs/comun/agentes-o-skills.md).
