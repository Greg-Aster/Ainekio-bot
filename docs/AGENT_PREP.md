# Ainekio Agent Prep

**Draft for owner review · 1 October 2026**

Hand this file to an agent before assigning Ainekio work. Keep one maintained
copy in MetaHuman OS; other repositories link here. This captures owner intent
and working methods, not a second roadmap or permission to implement everything.

## What we are building

Ainekio is a robot familiar that grows and learns through experience, with
memory, personality, curiosity and continuity. Its intelligence should survive
changes of model, host and body.

The LLM owns high-level goals and behavior choices. Give it useful context,
tools and feedback; do not replace its decisions with competing hardcoded
behavior policies. Execution owners translate those choices into supported
actions. Keep genuine physical limits, authentication and explicit user
permissions. Make rejection, cancellation, unsupported capabilities and uncertain
outcomes observable to the caller and model; do not silently discard an intended
action or pretend it succeeded. Do not invent additional safety layers without
an evidenced need and an explicit design decision.

Prefer lightweight, efficient, replaceable systems. Evaluate current models
against the actual workload and hardware; neither novelty nor an old benchmark
proves suitability. Improve the existing foundation before adding features:
reuse its owners, simplify its dependencies, and remove proven superseded paths.

## Read before work

1. Read the target repository's `AGENTS.md` and applicable local instructions.
2. Read the relevant [MetaHuman ownership boundaries](technical/MAINTAINED_SURFACE.md#critical-runtime-ownership-boundaries)
   and [integration/source map](implementation-plans/robot-active-operator-roadmap.md).
3. For body or gateway work, read [Body Control Integration](https://github.com/Greg-Aster/Ainekio-bot/blob/6437b24c0f91273aed160add0e42ac0ddbb5275c/docs/BODY_CONTROL_INTEGRATION.md)
   and follow its owner links. This pinned source is a reference snapshot; inspect
   the selected current revision before treating it as current.
4. Read the [single cross-repository queue and current baseline](https://github.com/Greg-Aster/merkin/blob/main/apps/ainekio/src/content/spec/project-guide.md#working-items).
   Use dated audits for evidence, not standing work orders.

This file carries project intent. Repository instructions govern work, maintained
owner documents govern detailed contracts, and actual entrypoints/tests establish
implementation. Report material conflicts instead of quietly choosing a different
architecture. Keep agent methods in repository instructions/docs; the public
website describes the project and its progress.

## How to work

- Inspect the actual branch, commit, remote refs, ancestry and local changes.
  Never assume `dev` contains newer `main` work or that a checkout matches the
  installed robot. Preserve other contributors' changes.
- Trace the real entrypoint, existing owner, consumers and tests before adding
  a manager, queue, store, policy or fallback. Repair the owner rather than
  building another path around it. Prove removal safety through references and
  runtime wiring.
- Agree the task's outcome and acceptance evidence. Keep the patch bounded;
  update the existing owner record and queue only where affected. Do not create
  another general plan, audit or status file for routine work.
- For website work, make review changes on `dev`; promote to `main` only when
  authorized. Do not create extra branches. Keep publishing, deployment and
  physical robot actions within the permissions of the task.
- Test the changed contract and relevant failure paths. Report what passed,
  failed or was not run, including pre-existing failures. Distinguish source,
  host/mock, installed-runtime and physical evidence. Never call an untested
  system green. Documentation and software consolidation need not wait for
  assembly.

## Task handoff

- **Outcome:** …
- **Scope:** repositories, target refs, existing changes, allowed edits/actions …
- **Acceptance:** observable result, checks and evidence level …
- **Completion:** concise diff summary, checks, remaining limits and decisions …
