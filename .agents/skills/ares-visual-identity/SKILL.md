---
name: ares-visual-identity
description: Define, extend, or audit the ARES visual identity for new screens, design tokens, dashboards, and component styling while preventing generic AI-generated SaaS aesthetics and preserving the normative prototype.
---

# ARES Visual Identity

Create a distinctive, operational, and defensible visual language for ARES. Do not make the product look like a generic AI template.

This skill consolidates the two identical user-provided drafts `skill2.txt` and `identidadevisualskill.txt`, preserving their intent while adapting the workflow to an established product.

## Start from evidence

Before changing UI:

1. Inspect existing tokens, styles, components, assets, routes, and screenshots.
2. Read the relevant Notion page and the documented prototype decisions.
3. Treat the existing prototype as normative for color, density, typography, component character, and information hierarchy unless the user explicitly approves a redesign.
4. Do not ask questions already answered by the repository or Notion.

If the request is a small correction or an additional state inside an established component, extend the existing system directly. Do not block the task with a new brand workshop.

## For a genuinely new visual surface

Before implementation, record a compact design-token plan:

- concept or domain anchor;
- semantic palette for light and dark contexts;
- typography roles and numeric alignment;
- spacing, density, grid, and responsive behavior;
- recurring signature element;
- motion rules and reduced-motion behavior;
- accessibility requirements.

Present the plan for confirmation when it changes established identity or involves material design judgment. Then implement it as tokens and reusable components, not scattered values.

## ARES character

- Operational intelligence, not science-fiction AI.
- Dense but calm; evidence and next action outrank decoration.
- Financial impact must look accountable: definition, source, period, freshness, attribution, and limitation remain visible.
- Use borders, spacing, hierarchy, typography, shape, and restrained color before shadows or effects.
- Icons come from Phosphor and communicate function; sparkle icons do not stand in for “AI”.
- Loading uses structural skeletons. Empty states explain the cause and the action that resolves it.

Read [references/visual-guardrails.md](references/visual-guardrails.md) for the anti-cliché audit before completing a major screen.

## Accessibility

- Meet WCAG AA contrast for text and interactive controls.
- Provide visible focus, keyboard navigation, appropriate touch targets, and reduced motion.
- Do not encode risk, attribution, agent state, or success only by color.
- Every chart with decision value needs a readable alternative.

## Final audit

Compare the result with the normative prototype and ask:

- Could this be mistaken for a generic AI/SaaS template?
- Did a library default override ARES tokens?
- Is decoration competing with evidence, state, or next action?
- Are all required states and permissions represented?

Correct material failures before declaring the UI complete.
