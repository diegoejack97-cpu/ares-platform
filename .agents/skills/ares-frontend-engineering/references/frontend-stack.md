# Frontend stack and visualization boundaries

## Authority

- Documentation root: https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3
- ARES Connect: https://app.notion.com/p/3c3e18aa7b0d81b68a0bff83ed7fe9df
- UX/UI and detailed screens: https://app.notion.com/p/3c3e18aa7b0d81acb2dbf39cbbc334b9
- Prototype and visual decisions: https://app.notion.com/p/3c5e18aa7b0d8149bdc3cef94037a25a

## Dependency decisions

| Concern | Choice | Boundary |
|---|---|---|
| UI primitives | shadcn/ui with accessible primitives | Copy and adapt to ARES tokens; do not preserve generic defaults |
| Styling | Tailwind CSS plus semantic CSS variables | No loose page-level palette |
| Operational tables | TanStack Table | Cursor pagination and server-state remain outside the table |
| Dashboard charts | Apache ECharts | Default renderer for standard business visualizations |
| Custom visualization | D3 | Use only the required modules for custom layouts and interaction |
| Spatial/high-volume rendering | deck.gl | Route-level lazy load; not part of the initial shell |
| Kanban | dnd-kit | Keyboard and non-drag alternative required |
| Icons | Phosphor Icons | Consistent size, weight, label, and accessible name |
| Forms | React Hook Form plus Zod/derived schema | Backend remains authoritative |
| E2E | Playwright | Cover critical business journeys and visual states |

## ARES visualization requirements

- Command Center: trends, risk/recovery summaries, funnel, stacked signals, heatmap, activity, and metric definitions.
- Radar: dense sortable/filterable table or cards with stable selection and live updates.
- Opportunity detail: intervention chain, evidence timeline, value attribution, and optional relational graph.
- Impact ARES: sale, influence, cost, and proven incremental value must remain distinct.
- Relationship graph: provide a list alternative and evidence provenance for every edge.

## Bundle and performance

- Import only ECharts chart/components used by a screen.
- Prefer D3 subpackages rather than the umbrella package where practical.
- Lazy-load deck.gl and heavy visualization routes.
- Dispose chart instances on unmount and use ResizeObserver for container changes.
- Respect reduced motion and disable ornamental animation.
