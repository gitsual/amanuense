---
name: nueva-pagina-confluence
description: Convierte un borrador local en una página nueva de Confluence, con la plantilla del equipo cuando el borrador lo pide («Plantilla: sí»). Úsala con cada carpeta salida/tareas/*-nueva-* del taller y para diseños de capacidad listos para pegar.
---

# Página nueva en Confluence

## Entradas

- Una carpeta de tarea del taller: `TAREA.md` y `LOCAL.md`.
- Si el borrador lleva `Plantilla: sí`, `TAREA.md` incluye la plantilla.

## Pasos

1. Lee `TAREA.md` entero. Sus reglas mandan sobre esta skill.
2. Si hay plantilla: usa sus secciones en su orden. Rellena cada una sólo con lo
   que diga el borrador o la Biblia; el resto, `> PENDIENTE:`. Los valores de
   ejemplo de la plantilla no son datos.
3. Si no hay plantilla: conserva la estructura del borrador y mejora la redacción.
4. Comprueba que la página no repite otra existente; si lo hace, enlázala.
5. Añade `## Registro de cambios`.
6. Guarda el resultado como `RESULTADO.md` y vuelve a ejecutar el taller.
7. Si `CAMBIOS.html` lista «Datos sin fuente», sustitúyelos por `> PENDIENTE:`.

## Salida

`RESULTADO.md`, y tras ejecutar el taller, `PARA-CONFLUENCE.html` para pegar.

## Nunca

Rellenar secciones de la plantilla con suposiciones para que «quede completa».
Una sección `PENDIENTE` es mejor que un dato falso.
