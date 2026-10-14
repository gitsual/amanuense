---
name: auditar-documentacion
description: Compara el export de Confluence con la documentación local y propone cómo dejarla coherente y reducida. Úsala antes de reescribir páginas o cuando alguien pregunte qué sobra, qué falta o qué está duplicado.
---

# Auditar la documentación

## Entradas

- Carpeta del taller con `1-export-confluence/`, `2-mi-documentacion/` y `3-biblia/`.

## Pasos

1. Ejecuta el taller (`amanuense.bat` en Windows, `./amanuense.sh` en Linux/macOS).
   Si el entorno tiene el buscador instalado, añade `--content`.
2. Lee `salida/informe.md`.
3. Propón, en este orden y sin ejecutar nada:
   - **Actualizar**: las tareas de `salida/tareas/*-actualizar-*`.
   - **Crear**: las de `*-nueva-*`.
   - **Fusionar**: cada «Duplicados en local» y «Contenido parecido con otro título»;
     di cuál se queda y qué se lleva del otro.
   - **Retirar**: de «Sólo en Confluence», las que nadie enlaza o repiten a otra.
     Son candidatas: la decisión es humana.
   - **Asignar a mano**: «Instrucciones sin página destino» (¿página renombrada?).
4. Para cada contradicción, cita las dos frases y di cuál dice la Biblia.

## Salida

Una lista corta con las cinco secciones anteriores y, al final, cuántas páginas
quedarían en Confluence si se aprueba todo.

## Nunca

Borrar, mover ni publicar. Esta skill sólo propone.
