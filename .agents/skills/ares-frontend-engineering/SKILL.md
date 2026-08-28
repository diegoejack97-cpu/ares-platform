---
name: ares-frontend-engineering
description: Implement or review ARES React/TypeScript screens, dashboards, charts, tables, Kanban interactions, responsive states, and frontend architecture while preserving the Notion contracts and the established visual system.
---

# ARES Frontend Engineering

Build production frontend behavior from the ARES specifications without allowing a UI library to redefine the product.

## Before editing

1. Inspect the repository and the relevant Notion specification. The ARES documentation tree is the product and technical source of truth.
2. Identify the route, role, API contract, events, permissions, acceptance criteria, and mandatory loading, empty, stale, partial, conflict, capability-missing, and error states.
3. If the work changes visual language or introduces a new visual surface, also use `ares-visual-identity`.

## Fixed direction

- React + TypeScript.
- Server state through TanStack Query and typed API contracts generated from OpenAPI.
- Tailwind CSS and shadcn/ui with accessible primitives, adapted to ARES tokens rather than used with default styling.
- TanStack Table for Radar, audit, approval, intervention, and operational data tables.
- dnd-kit for the pipeline/Kanban, including keyboard operation and an equivalent non-drag action.
- Phosphor Icons for product iconography.
- React Hook Form with Zod or schemas derived from the canonical API contract.
- Playwright for critical end-to-end journeys and accessibility checks.

Read [references/frontend-stack.md](references/frontend-stack.md) when choosing a visualization library or adding a new frontend dependency.

## Visualization routing

- **ECharts first:** KPI trends, bullet-style comparisons, bars, stacked bars, funnel, heatmap, gauge, standard relationship graph, and interactive dashboard charts.
- **D3 selectively:** bespoke SVG, scales, shapes, layouts, force simulation, annotation, or interaction that ECharts cannot express cleanly. Prefer small focused D3 modules over a second chart framework.
- **deck.gl selectively:** maps, geospatial layers, large point/arc/polygon datasets, or WebGL-heavy visualizations. Lazy-load it behind the route or feature that needs it.
- Never use all three for the same widget merely because they are available. Keep the normalized data contract separate from the renderer.

## UI contract

- Business rules, authorization, metric formulas, attribution decisions, and critical validations stay in the backend.
- A mutation must surface pending, success, failure, retry, conflict, and correlation information where applicable.
- Capability absence is explained before interaction, not discovered after a failed click.
- `incremental_value = null` is rendered as “não comprovado”, never as zero or generated revenue.
- Color never carries meaning alone. Provide labels, shapes, patterns, or textual status.
- Charts that drive decisions require an accessible table or list view.
- Avoid eager imports of ECharts, D3, and deck.gl in the application shell.

## Verification

- Run the relevant lint, typecheck, component, accessibility, and E2E checks that exist.
- Verify the real page in a browser at desktop, tablet, and essential mobile width.
- Check keyboard navigation, focus visibility, chart alternative, empty/error states, console errors, and layout overflow.
- Compare the result with the Notion prototype and acceptance criteria before declaring completion.
