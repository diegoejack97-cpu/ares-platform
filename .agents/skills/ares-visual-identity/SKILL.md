---
name: ares-visual-identity
description: Define, extend, audit, and evolve the ARES visual identity across the complete product, including design tokens, application shell, dashboards, charts, tables, forms, AI surfaces, and reusable components, while preventing generic AI-generated SaaS aesthetics and preserving the normative prototype.
---

# ARES Visual Identity

Create a distinctive, operational, coherent, and defensible visual language for ARES.

ARES must not look like a generic AI-generated SaaS product.

This skill defines the visual decision framework for the complete ARES product, including screens, dashboards, navigation, components, data visualization, operational surfaces, and intelligence experiences.

## Start from evidence

Before changing UI:

1. Inspect existing tokens, styles, components, assets, routes, screenshots, layouts, and visual primitives.
2. Read the relevant Notion page and the documented prototype decisions.
3. Treat the existing prototype as normative for color, density, typography, component character, and information hierarchy unless the user explicitly approves a redesign.
4. Inspect existing visual patterns before introducing new ones.
5. Do not ask questions already answered by the repository or Notion.
6. Do not invent metrics, flows, states, terminology, or product behavior merely to improve composition.

If the request is a small correction or an additional state inside an established component, extend the existing system directly. Do not block the task with a new brand workshop.

## System-wide visual identity

ARES must be treated as one coherent product, not as a collection of independently designed screens.

Visual improvements must consider the complete product experience:

- application shell;
- navigation;
- headers;
- dashboards;
- CRM views;
- lead views;
- opportunity views;
- pipeline;
- Kanban;
- operational queues;
- tables;
- forms;
- filters;
- charts;
- drawers;
- modals;
- alerts;
- AI surfaces;
- command interfaces;
- empty states;
- loading states;
- stale states;
- degraded states;
- errors;
- onboarding;
- reports;
- settings.

Do not redesign individual pages in isolation when the underlying visual problem belongs to the system.

When a recurring visual problem is identified, solve it at the token, primitive, component, chart-system, or layout-system level first.

The same hierarchy, spacing, typography, interaction logic, density, chart language, semantic meaning, and visual character must propagate consistently throughout ARES.

A mature ARES screen must feel clearly related to every other ARES screen even when their business functions are different.

## Design-system-first rule

For broad redesign or visual evolution work, do not start by restyling every page independently.

Work in this order:

1. audit the complete interface;
2. identify repeated visual problems;
3. identify which current patterns must be preserved;
4. define or refine design tokens;
5. define layout primitives;
6. define navigation and application shell behavior;
7. define reusable analytical surfaces and interaction patterns;
8. define the ARES chart system;
9. define table, list, filter, form, and operational queue patterns;
10. define AI and intelligence presentation patterns;
11. migrate existing screens progressively to the shared system.

Do not solve the same visual problem separately in multiple pages.

Prefer one reusable system-level solution.

## For a genuinely new visual surface

Before implementation, record a compact design-token plan:

- concept or domain anchor;
- semantic palette for light and dark contexts;
- typography roles and numeric alignment;
- spacing, density, grid, and responsive behavior;
- recurring signature element;
- motion rules and reduced-motion behavior;
- accessibility requirements.

Present the plan for confirmation only when it changes established identity or involves material design judgment that is not already resolved by the repository or Notion.

Then implement it as tokens and reusable components, not scattered values.

## ARES character

- Operational intelligence, not science-fiction AI.
- Dense but calm.
- Evidence and next action outrank decoration.
- Financial impact must look accountable: definition, source, period, freshness, attribution, and limitation remain visible.
- Use borders, spacing, hierarchy, typography, shape, and restrained color before shadows or effects.
- Icons come from Phosphor and communicate function.
- Sparkle icons do not stand in for “AI”.
- Loading uses structural skeletons.
- Empty states explain the cause and the action that resolves it.
- The interface should feel deliberate, precise, analytical, premium, and operational.
- Visual sophistication must come from composition, hierarchy, typography, information density, interaction, and data visualization rather than decoration.

Read [references/visual-guardrails.md](references/visual-guardrails.md) for the anti-cliché audit before completing a major screen.

## Composition principles

ARES interfaces must be composed from operational and analytical questions, not from the component library.

Prefer:

- information hierarchy over decoration;
- continuous analytical workspaces over disconnected card grids;
- sections, dividers, alignment, typography, and whitespace over nested cards;
- compact KPI strips when metrics belong to the same analytical context;
- dense but readable tables for operational work;
- contextual filters close to the data they affect;
- progressive disclosure for secondary detail;
- side panels or drill-down surfaces for investigation;
- asymmetric layouts when information importance justifies it;
- clear focal points on strategic screens;
- intentional visual rhythm between primary, secondary, and tertiary information.

Avoid:

- dashboards composed primarily of equal-sized cards;
- cards inside cards;
- excessive `rounded-xl`, `rounded-2xl`, or pill-shaped containers;
- large empty regions created only to make the interface appear minimal;
- decorative hero areas in operational screens;
- excessive shadows, glow, blur, or glassmorphism;
- arbitrary gradients;
- visually identical sections repeated throughout a page;
- layouts that resemble default shadcn, Tailwind, admin-dashboard, or generic SaaS templates;
- symmetrical grids that give equal weight to information of very different importance.

Do not convert every metric into an isolated KPI card.

The importance, relationship, urgency, and actionability of information should determine layout.

Primary analytical surfaces must dominate the viewport when their business importance justifies it.

Secondary widgets must support the main operational question, not compete with it.

Tables that drive action should feel like operational workspaces, not generic admin tables.

## ARES visual signature

ARES must develop recurring visual characteristics that make the product recognizable without relying on its logo.

The signature should emerge from a consistent combination of:

- typography;
- density;
- information hierarchy;
- analytical composition;
- navigation behavior;
- chart treatment;
- semantic color;
- borders;
- spacing;
- interaction patterns;
- operational states;
- evidence presentation.

Do not create a decorative gimmick merely to satisfy the requirement for a “signature element”.

The identity should come from the system as a whole.

A screenshot of a mature ARES screen should not be easily confused with another generic CRM, BI dashboard, admin panel, or AI-generated SaaS interface.

## Data visualization language

Charts are decision-support interfaces, not decoration.

Before selecting a visualization, identify the business question it must answer.

Examples:

- “How is performance evolving?” → time series;
- “Where is the pipeline losing opportunities?” → funnel, stage conversion, or Sankey;
- “Which opportunities deserve attention?” → scatter plot or opportunity matrix;
- “What changed abnormally?” → time series with anomaly markers;
- “How uncertain is the forecast?” → forecast line with confidence interval;
- “Where are conversion patterns concentrated?” → heatmap;
- “What contributed to the change?” → waterfall;
- “How are scores distributed?” → histogram or distribution chart;
- “How does one segment compare to another?” → grouped comparison or small multiples;
- “Where are bottlenecks accumulating?” → stage flow, queue aging, heatmap, or temporal distribution.

ECharts is the standard visualization engine.

Use advanced ECharts capabilities when they improve analysis:

- `dataset`;
- transforms;
- `markLine`;
- `markArea`;
- `markPoint`;
- `visualMap`;
- `dataZoom`;
- `brush`;
- `axisPointer`;
- linked interactions;
- Sankey;
- heatmap;
- scatter;
- custom series;
- confidence bands;
- annotations;
- comparison periods;
- anomaly markers;
- mixed/composed charts.

Do not use advanced visualization merely to appear sophisticated.

Avoid 3D charts unless spatial depth represents actual information.

Avoid pie or donut charts when comparison between values is the primary task.

Every visualization with business value should support appropriate interaction when useful, such as:

- contextual tooltip;
- filtering;
- drill-down;
- series toggle;
- time comparison;
- zoom;
- selection;
- cross-filtering;
- linked highlighting.

Tooltips must communicate business meaning, not only raw values.

A chart must never exist only because “the dashboard needs a chart”.

## Unified ARES chart system

All analytical visualizations must belong to one shared ARES chart language.

Do not rely on the default ECharts visual theme.

Create and reuse centralized configuration for:

- typography;
- semantic palette;
- chart grids;
- axes;
- legends;
- tooltips;
- annotations;
- data zoom;
- transitions;
- comparison states;
- forecast;
- confidence;
- risk;
- anomaly;
- loading;
- empty;
- error;
- responsiveness;
- numeric formatting;
- currency formatting;
- percentage formatting;
- date/time formatting.

Do not create isolated ECharts themes per screen.

Business context may alter the visualization, but the underlying visual language must remain consistent.

Charts from different screens should feel like members of the same product.

If a chart can be visually mistaken for a default ECharts demo, its visual treatment is incomplete.

## Intelligence surfaces

AI must not be represented as a separate decorative layer.

ARES intelligence should appear contextually inside the workflow.

Prefer:

- contextual insights;
- recommendations;
- next-best-action;
- risk indicators;
- anomaly explanations;
- forecast explanations;
- opportunity scoring;
- supporting evidence;
- confidence;
- agent state;
- execution trace;
- outcome feedback.

Do not represent every AI capability as a chatbot.

Use chat only when conversation is actually the correct interaction model.

Intelligence must feel integrated into the operational product rather than attached to it.

Do not use visual effects to imply “AI”.

AI state must remain accountable and understandable.

## Screen-family migration

When performing a broad visual evolution, migrate the product progressively by families.

Recommended order:

1. foundation and tokens;
2. application shell and navigation;
3. shared visual primitives;
4. chart system;
5. dashboards and observability;
6. opportunities and detail views;
7. CRM and leads;
8. pipeline and Kanban;
9. operational tables and queues;
10. forms and configuration surfaces;
11. intelligence and agent surfaces;
12. reports and secondary screens.

Each family must reuse the same visual system.

Do not create a new visual language for each family.

Prefer small, reviewable migrations over one uncontrolled rewrite.

## Accessibility

- Meet WCAG AA contrast for text and interactive controls.
- Provide visible focus, keyboard navigation, appropriate touch targets, and reduced motion.
- Do not encode risk, attribution, agent state, or success only by color.
- Every chart with decision value needs a readable alternative.
- Preserve semantic HTML and accessible labels.
- Ensure interactive charts remain usable without relying exclusively on pointer hover.

## Visual validation loop

Significant visual work is not complete after implementation.

For major screens or meaningful visual changes, follow:

IMPLEMENT
→ RENDER
→ INSPECT
→ CRITIQUE
→ REFINE

When browser tooling or Playwright is available, inspect the rendered interface rather than relying only on source code.

Evaluate at representative viewport sizes:

- 1920x1080;
- 1440x900;
- 1280x800;
- tablet.

Inspect specifically for:

- hierarchy;
- density;
- alignment;
- spacing;
- excessive whitespace;
- visual monotony;
- overflow;
- text truncation;
- inconsistent radius;
- chart sizing;
- chart readability;
- tooltip positioning;
- responsive degradation;
- loading states;
- empty states;
- stale states;
- degraded states;
- errors;
- hover;
- focus;
- keyboard navigation;
- contrast;
- unnecessary decoration;
- generic library defaults.

For major redesign work, perform multiple visual refinement passes.

Do not declare a major UI task complete solely because:

- it compiles;
- tests pass;
- components render;
- the screenshot contains no obvious errors.

Visual quality requires visual inspection.

## Final audit

Compare the result with the normative prototype and ask:

- Could this be mistaken for a generic AI/SaaS template?
- Did a library default override ARES tokens?
- Is decoration competing with evidence, state, or next action?
- Are all required states and permissions represented?
- Is the layout driven by information or by a card grid?
- Could any card be removed and replaced by hierarchy, spacing, or a divider?
- Does each chart answer a specific business question?
- Does every major chart visually belong to ARES?
- Is whitespace intentional rather than accidental?
- Is the most important information visually dominant?
- Does the screen remain recognizable as ARES without the logo?
- Are repeated problems solved at the system level instead of locally?
- Is the intelligence experience integrated with the workflow instead of attached as decoration?
- Do light and dark modes feel like the same product rather than separate themes?

Correct material failures before declaring the UI complete.
