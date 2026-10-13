# Brick IHM — documentación, agentes y skills

Repo común del equipo para todo lo que escribe o lee una IA. Confluence (MIND)
sigue siendo la fuente de verdad publicada; este repo guarda su copia de trabajo,
las reglas y los procedimientos para mantenerla.

```
docs/
  biblia/        lo que manda: arquitectura de referencia, publicación en Nexus,
                 estándares de repos. Si algo lo contradice, gana esto.
  comun/         documentación común a todos los bricks (procesos, nomenclatura,
                 plantillas de trabajo diario, guías).
  brick-hmi/     documentación propia del Brick IHM, una página por fichero,
                 con el mismo título que su página de Confluence.
agentes/         un fichero por rol: quién hace qué, con qué skills y qué aprobación.
skills/          un procedimiento por carpeta (SKILL.md): pasos, entradas, salidas.
AGENTS.md        reglas que cualquier agente lee antes de tocar el repo.
```

## Agentes y skills en cada herramienta

`skills/` y `agentes/` son la única fuente: se editan ahí. Para que cada
herramienta los encuentre en su formato, se regeneran con:

```
amanuense agents RUTA_DEL_REPO
```

| Herramienta | Skills | Agente | Instrucciones |
| --- | --- | --- | --- |
| Claude Code | `.claude/skills/` | `.claude/agents/` | `CLAUDE.md` → `@AGENTS.md` |
| Codex | `.agents/skills/` | `.codex/agents/*.toml` | `AGENTS.md` |
| Gemini CLI | `.agents/skills/` | `.gemini/agents/` | `AGENTS.md` (vía `.gemini/settings.json`) |
| GitHub Copilot | `.agents/skills/` | `.github/agents/` | `AGENTS.md` |

Este esqueleto ya los trae generados. Abre el repo con cualquiera de ellas y pide,
por ejemplo, «usa la skill auditar-documentacion».

## Cómo se trabaja

1. Exporta la sección de Confluence a Word y pásala por el taller
   (`amanuense.bat`, ver la guía de amanuense) junto a `docs/`.
2. El informe dice qué actualizar, qué es nuevo y qué sobra.
3. Cada página se reescribe con la skill que toca y pasa por tu aprobación
   (`CAMBIOS.html`) antes de pegarse en Confluence.
4. La versión aprobada se guarda aquí, en `docs/`, con un commit por página.

## Reglas que no se negocian

- Nada se publica en Confluence sin aprobación humana.
- Ninguna IA inventa datos: lo que falta queda como `> PENDIENTE`.
- Una página, un tema: si algo ya está en otra página, se enlaza, no se copia.
- Los cambios de reglas van a `AGENTS.md` o a la `SKILL.md`, no al chat:
  así cualquier persona y cualquier agente obtienen el mismo resultado.
