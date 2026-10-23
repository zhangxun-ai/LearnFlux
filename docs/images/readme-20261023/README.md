# README screenshots, 2026-10-23

These PNGs are browser captures of the current working-tree UI, not design mockups.

The captures include local development changes not yet merged into main, notably result typography, delivery status and source-scoped comparison. Publishing these screenshots does not publish those application changes; the root README marks their availability explicitly.

| File | Current source | Capture |
| --- | --- | --- |
| 01-import.png | src/web/static/index.html and linked production assets | Single-content import and recent tasks |
| 02-result.png | src/web/templates/transcript.html, base.html and linked production assets | Summary typography and configured delivery controls |
| 03-compare.png | src/web/static/history.html and js/history-evidence.js | Select two records, ask, and inspect source evidence |
| 04-collections.png | src/web/static/collections.html and js/collections.js | Completed three-lesson course, chapter panel, series interpretation and table of contents |
| 05-reading.png | src/web/static/reading.html and js/reading.js | Immersive two-page reading of an authored example document |
| 06-writing.png | src/web/static/focus-studio.html and js/focus-studio.js | Rain scene, authored example diary, ambient controls and focus timer |
| 07-history.png | src/web/static/history.html and linked production assets | Full history header, hanging recent-learning cards, filters and record list |
| 08-reading-library.png | src/web/static/reading.html and js/reading.js | Four example library documents and continue-reading progress |

Viewport: 1440 × 1000, light theme. Captured with browser-skill in an Agent Window.

To keep private data out of the public README, the unchanged pages and assets were served on an isolated loopback-only demonstration server. API responses contain authored example records, body text, answers and delivery states. No private database, production API credential, real view token or source media was loaded by that server. A displayed Feishu state is an illustration, not a claim that a new installation already has Feishu configured. No model or third-party processing was called to produce these captures.

The five additional captures cover existing course, reading, writing and history surfaces. They use example course/document payloads and a diary typed through the real editor. The library format labels illustrate supported types; they do not constitute a new import/conversion acceptance test for each format. All eight captures were individually inspected for rendering and visible private content.

Refresh by rendering the current production pages with a non-private dataset; use the actual browser controls to reach the target states, capture the page and inspect every resulting image. Update the date and this provenance note together. Do not replace them with generated mockups or screenshots containing real credentials or private records.
