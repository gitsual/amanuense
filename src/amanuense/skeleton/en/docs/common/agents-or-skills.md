# Agent or skill?

This is an organizational decision, not a technical one: both are text files
that an AI reads. The difference is what they describe.

| | Skill | Agent |
| --- | --- | --- |
| Describes | **How** a task is done | **Who** does it, with what access and under which approval |
| Form | Steps, inputs, output, "never" | Role, skills it uses, permissions, approvals |
| Reuse | By any agent or person | A specific role (curator, coordinator...) |
| Example | Update a Confluence page | Documentation curator |

## Rule of thumb

- If you can write it as a recipe with steps and a verifiable result,
  it is a **skill**.
- If you need to say "this one can read Jira but not publish" or "the
  documentation owner approves this", it is an **agent**.
- If an agent piles up skills that have nothing to do with each other, it is
  two roles: split it. An agent with a few related skills is more reliable
  than one with a hundred.

## Where corrections go

When an AI gets something wrong, the fix goes into the `SKILL.md` or the agent
file, not into the chat. That way the next user, person or bot, gets the same result.

## From here to Teams or Power Automate

One bot per role is an agent: its file says which skills it uses and who approves what.
The skills are the same ones the team uses locally; they are not rewritten for
each tool.
