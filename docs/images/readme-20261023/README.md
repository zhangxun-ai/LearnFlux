# README screenshots, 2026-10-23

These PNGs are browser captures of the current working-tree UI, not design mockups.

The captures include local development changes not yet merged into main, notably result typography, delivery status and source-scoped comparison. Publishing these screenshots does not publish those application changes; the root README marks their availability explicitly.

| File | Current source | Capture |
| --- | --- | --- |
| 01-import.png | src/web/static/index.html and linked production assets | Single-content import and recent tasks |
| 02-result.png | src/web/templates/transcript.html, base.html and linked production assets | Summary typography and configured delivery controls |
| 03-compare.png | src/web/static/history.html and js/history-evidence.js | Select two records, ask, and inspect source evidence |

Viewport: 1440 × 1000, light theme. Captured with browser-skill in an Agent Window.

To keep private data out of the public README, the unchanged pages and assets were served on an isolated loopback-only demonstration server. API responses contain authored example records, body text, answers and delivery states. No private database, production API credential, real view token or source media was loaded by that server. A displayed Feishu state is an illustration, not a claim that a new installation already has Feishu configured. No model or third-party processing was called to produce these captures.

Refresh by rendering the current production pages with a non-private dataset; use the actual browser controls to reach the target states, capture the page and inspect every resulting image. Update the date and this provenance note together. Do not replace them with generated mockups or screenshots containing real credentials or private records.
