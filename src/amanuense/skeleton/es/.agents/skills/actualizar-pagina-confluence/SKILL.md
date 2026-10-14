---
name: actualizar-pagina-confluence
description: Reescribe una página de Confluence aplicando sólo sus «Instrucciones de actualización», sin inventar nada, y la deja lista para aprobar y pegar. Úsala con cada carpeta salida/tareas/*-actualizar-* del taller.
---

# Actualizar una página de Confluence

## Entradas

- Una carpeta de tarea del taller: `TAREA.md` (reglas, instrucciones, página
  actual y Biblia), `ACTUAL.md` y `LOCAL.md`.

## Pasos

1. Lee `TAREA.md` entero. Sus reglas mandan sobre esta skill.
2. Haz una lista de los cambios que piden las instrucciones. Nada más cambia.
3. Reescribe la página partiendo de `ACTUAL.md` y aplica sólo esa lista.
4. Contrasta el resultado con la Biblia; si algo choca, `> CONFLICTO:` y deja el texto actual.
5. Quita repeticiones dentro de la página; si un bloque vive en otra, enlázala.
6. Añade `## Registro de cambios` con una viñeta por cambio.
7. Guarda el resultado como `RESULTADO.md` en la carpeta de la tarea.
8. Vuelve a ejecutar el taller para generar `CAMBIOS.html` y `PARA-CONFLUENCE.html`.
9. Si `CAMBIOS.html` lista «Datos sin fuente», quita o justifica cada uno antes de entregarlo.

## Salida

`RESULTADO.md`. La persona revisa `CAMBIOS.html` y, si lo aprueba, pega
`PARA-CONFLUENCE.html` en Confluence.

## Nunca

Publicar tú en Confluence, ni completar datos que no estén en la tarea.
