---
name: graphify-codebase
description: Build, update, or query a Graphify knowledge graph for the ARES codebase when the user explicitly requests architecture mapping, dependency paths, graph generation, or graph-backed codebase analysis.
---

# Graphify Codebase

Use Graphify as an optional development aid, not as a runtime dependency of ARES and not as a replacement for direct verification.

## Boundaries

- Trigger for explicit graph generation, update, query, path, or architecture-mapping requests. Do not hijack ordinary file lookup or simple code questions.
- Prefer project-scoped configuration and keep Graphify out of production dependencies.
- Do not enable strict mode or Git hooks by default.
- Do not install or upgrade `graphifyy` without user approval.
- Do not send documents, media, database schemas, or source-derived content to an external model without disclosing destination, data scope, and expected cost and receiving approval.
- Do not require or initiate subagents unless the user or active project instructions authorize them.

## Workflow

1. Check for `graphify-out/graph.json`.
2. If it exists and the user asks a graph question, use the narrowest `graphify query`, `graphify path`, or `graphify explain` command.
3. If a rebuild is requested, inspect scope and sensitive files before running.
4. If the CLI is absent, report that the official package is `graphifyy` and request approval before installation.
5. On Windows PowerShell, use `graphify .`, not `/graphify .`.
6. Treat EXTRACTED and INFERRED relationships differently in conclusions and verify important inferred paths against source.
7. Keep generated output uncommitted unless the user explicitly requests it as a repository artifact.

Read [references/upstream.md](references/upstream.md) before installation, upgrade, semantic extraction, hooks, or CI integration.
