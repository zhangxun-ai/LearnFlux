# Landing Page Brief

## Scope

Implement the local product introduction at `/` only. Keep the workbench at `/add_task_by_web` and all other page designs unchanged until the user reviews and accepts this landing page.

## Approved Direction

The user selected `approved-reference.png`. Carry forward its warm white canvas, deep green editorial headline, fresh natural illustration, left-aligned hero, clear primary action, and three-step learning story. The reference's second screen shows a future workbench concept; it is not a request to redesign that page in this phase.

## Landing Story

1. Introduce LearnFlux as a personal AI learning workbench.
2. Show the real path: import material → use transcripts and AI explanations with audio/video → organize notes.
3. Link the main action to the existing `/add_task_by_web` route.

Do not claim that the product has publicly launched, is hosted, is open source, has customers, or has a price. The source-release and business model are undecided. Keep the page scoped to the current user's local product; other product pages remain unchanged.

## Visual Inventory

| Element | Implementation | Notes |
| --- | --- | --- |
| Brand and navigation | Green leaf mark with semantic HTML/CSS | Product-feature and workflow anchors plus the existing workbench route |
| Hero headline and actions | Live text and links | The landscape remains an original image; the overlaid interface sample is a static, screen-reader-labeled illustration |
| Countryside scene | `src/web/static/images/landing/learnflux-meadow-hero-v2.png` | Original imagegen asset; prompt is embedded in image metadata |
| Learning flow | Compact ordered strip at the hero's lower edge | Import, understand, review and keep useful notes |
| Capability summary | Two-column semantic article list | Existing capabilities only; no graph or insight promotion |
| Footer | Product name and current personal-workbench description | No open-source, GitHub-star, launch, or pricing claim |

## Type and Geometry

- Large left-aligned serif headline; system sans-serif for body and controls.
- Warm paper ground, leaf-green primary action, light sage sections, restrained borders.
- Desktop hero uses the countryside image as a full scenic background, with the headline and actions at the upper left, a wide workbench preview near the lower edge, and the three-step flow strip along the bottom.
- Mobile stacks the hero copy above a compact preview and vertical flow strip; the preview hides its sidebar and notes pane to preserve reading space.
- The preview shows existing learning features only and avoids removed diagram and insight entry points.
- Other pages do not inherit this brief until reviewed separately.
