# ¿Agente o skill?

Es una decisión de organización, no técnica: los dos son ficheros de texto que
una IA lee. La diferencia es qué describen.

| | Skill | Agente |
| --- | --- | --- |
| Describe | **Cómo** se hace una tarea | **Quién** la hace, con qué acceso y bajo qué aprobación |
| Forma | Pasos, entradas, salida, «nunca» | Rol, skills que usa, permisos, aprobaciones |
| Se reutiliza | Por cualquier agente o persona | Es un rol concreto (curador, coordinador…) |
| Ejemplo | Actualizar una página de Confluence | Curador de documentación |

## Regla práctica

- Si lo puedes escribir como una receta con pasos y un resultado comprobable,
  es una **skill**.
- Si necesitas decir «este puede leer Jira pero no publicar» o «esto lo aprueba
  la responsable de documentación», es un **agente**.
- Si un agente acumula skills que no tienen que ver entre sí, son dos roles:
  pártelo. Un agente con pocas skills relacionadas es más fiable que uno con cien.

## Dónde van las correcciones

Cuando una IA se equivoca, el arreglo va a la `SKILL.md` o al fichero del agente,
no al chat. Así el siguiente que la use, persona o bot, obtiene el mismo resultado.

## De aquí a Teams o Power Automate

Un bot por rol es un agente: su fichero dice qué skills usa y qué aprueba quién.
Las skills son las mismas que usa el equipo en local; no se reescriben para cada
herramienta.
