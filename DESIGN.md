---
name: "LearnFlux"
description: "A calm, illustrated learning workspace for local use."
colors:
  paper: "#FDFCF8"
  white: "#FFFFFF"
  ink: "#123D32"
  body: "#33443D"
  muted: "#64756D"
  leaf: "#337B62"
  leaf-dark: "#23634F"
  sage: "#E7F1E9"
  line: "#E3EAE4"
typography:
  display:
    fontFamily: "Georgia, Songti SC, STSong, Noto Serif CJK SC, serif"
    fontSize: "clamp(2.35rem, 3vw, 3.5rem)"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.045em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  button: "999px"
  preview: "22px"
  section: "28px"
spacing:
  sm: "10px"
  md: "18px"
  lg: "32px"
  xl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.leaf}"
    textColor: "{colors.white}"
    rounded: "{rounded.button}"
    padding: "0 24px"
    height: "52px"
  button-secondary:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button}"
    padding: "0 24px"
    height: "52px"
  preview-surface:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.preview}"
---

# Design System: LearnFlux

## 历史记录参考稿对齐（2026-10-18）

历史记录以用户提供的 1586 × 992 参考图为视觉验收依据。桌面侧栏 293px，正文从 x330 开始；标题、搜索、两行筛选、最近学习晾衣绳与全部记录表格保持原稿顺序。筛选与最近学习默认展开；性能缓存、分页大小和当页选择保留。系统导航紧随心流空间，不能被自动推到底部。

最近学习使用约 216px 宽的纸质卡片、190 × 122px 插画和木夹晾衣绳；表格使用同一条记录的同一插画缩略图。装饰不遮盖控件，不制造示例学习记录。插画资源位于 `src/web/static/images/history/`，由内置 imagegen 按参考图分别重建为窗台猫、书与茶、湖边小镇、书房猫、樱花电车、海岸六种场景，并提供顶部山野和侧栏花丛栅栏背景。纹理细节属于重建插画，不能宣称像素完全一致。


## Overview

**Creative North Star: “The Illustrated Learning Path.”**

This specification covers the public landing page and the local workbench. The visual direction follows the references the user selected: bright countryside illustrations, generous breathing room, and a clear path from importing material to keeping useful knowledge. The landing illustration supports the product story while each workbench page applies the same paper, leaf-green, and sage palette to its real controls and content.

The pages describe LearnFlux as a personal AI learning workspace used locally. They do not imply that the product has launched publicly or make claims about pricing, customers, source licensing, or hosted availability. Workbench styling is additive and preserves the existing routes, DOM contracts, and feature behavior.

**Key Characteristics:**

- Warm paper surfaces, readable dark-green text, and restrained leaf-green actions.
- An original countryside illustration with a compact, screen-reader-labeled interface preview and a three-step strip along the hero's lower edge.
- Editorial Chinese headlines paired with familiar system body text.
- Clear actions that lead into the existing local learning workflow.

## Colors

The palette keeps the page light and quiet; green marks the learning path and the main action.

### Primary

- **Leaf Green** (`#337B62`): Primary actions, active preview navigation, and small progress accents.
- **Deep Leaf** (`#23634F`): Hover state and stronger link emphasis.

### Secondary

- **Soft Sage** (`#E7F1E9`): Selected states and the preview sidebar surface.

### Neutral

- **Paper White** (`#FDFCF8`): Main page background and the soft overlay above the landscape.
- **White** (`#FFFFFF`): Workbench content and preview surfaces.
- **Ink Green** (`#123D32`): Main headline and high-emphasis text.
- **Body Ink** (`#33443D`): Supporting copy.
- **Muted Green Gray** (`#64756D`): Secondary labels and supporting detail.
- **Soft Divider** (`#E3EAE4`): Fine borders and separators.

## Typography

**Display Font:** Georgia, Songti SC, STSong, Noto Serif CJK SC, serif
**Body Font:** System UI, PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif

**Character:** The serif wordmark and handwritten Chinese copy give the opening a calm, personal character. The system sans-serif keeps the learning preview familiar and easy to scan.

### Hierarchy

- **Brand** (700, `clamp(2.35rem, 3vw, 3.5rem)`, Georgia / Song): LearnFlux wordmark.
- **Tagline** (600, `clamp(1.45rem, 1.75vw, 2.15rem)`, Kai / Song): The handwritten-style brand promise.
- **Body** (400, `1rem`, `1.65`): Explanatory copy and step descriptions.
- **Preview** (400–650, `0.72rem`–`1rem`): Compact product-interface details.

## Layout

The landing page is a single, viewport-filling illustrated composition. It has no top navigation or extra feature copy: a LearnFlux wordmark and two short lines of brand copy sit over the landscape, a handwritten note balances the right side, a wide learning-interface preview occupies the middle, and the three-step workflow rests at the bottom. The preview is the unobtrusive entry to `/add_task_by_web`.

The workbench uses a 244px sidebar with three navigation groups and a flexible content area. Page bodies use responsive, readable content widths and white cards on warm paper. The study form, series workspace, player, review pages, reading shelf, immersive reader, writing studio, history, and settings keep their existing controls and interaction states. At narrower widths the content stacks, the book grid reduces columns, and focus controls move below the editor.

The hero fills the viewport up to 820px and uses the panoramic artwork on extra-wide screens. At widths up to 1200px, the preview hides its note column to keep the transcript readable; below 760px it also hides the miniature sidebar and stacks the workflow steps. The mobile preview keeps the image and transcript side by side with readable text.

## Elevation & Depth

Depth comes from the illustrated landscape, a light translucent paper overlay, thin borders, and soft ambient shadows. Keep the page airy; reserve stronger separation for the learning-interface preview.

### Shadow Vocabulary

- **Workbench preview** (`0 16px 48px rgba(38, 75, 52, 0.14)`): Separates the preview from the illustrated hero.
- **Primary action** (`0 9px 22px rgba(42, 111, 82, 0.16)`): Gives the main action a quiet lift.

## Shapes

Workbench buttons use a pill silhouette (`999px`). The interface preview uses a soft `22px` radius. Fine green-gray borders define panels without heavy outlines. The landscape fills and clips to the hero bounds so its edges stay contained behind the copy and preview.

## Components

### Navigation

The landing page has no visible top navigation. Keep its brand lockup, right-side handwritten line, miniature workbench preview, and workflow strip aligned with the reference composition. The preview itself opens the workbench. The workbench uses a light sage sidebar with a leaf mark, clear group labels, simple line icons, and a soft green active state.

### Buttons

- **Primary:** Leaf-green fill, white text, pill shape, `52px` high, and `24px` horizontal padding.
- **Secondary:** White translucent fill, ink-green text, fine sage border, and the same pill shape.
- **Hover / Focus:** Darken the primary fill slightly; provide a visible keyboard outline with offset.

### Cards / Containers

- **Workbench preview:** White surface with a fine sage border, `22px` radius, and soft ambient shadow. Its miniature controls are illustrative; the card links to the real workbench.
- **Workflow strip:** A soft paper gradient at the landscape's lower edge, with three numbered steps and fine separators.
- **Workbench cards:** White surface, fine sage border, `15–18px` radius, and low soft shadow. Use the same card language for input, review, reading, and configuration surfaces.

## Workbench Details

- Warm paper (`#FDFCF8`) is the page background, white is the content surface, and pale sage (`#F2F7F2`) distinguishes navigation.
- Deep green (`#123D32`) carries headings; body copy uses a muted green-gray; leaf green (`#337B62`) marks the primary action and current selection.
- Keep forms, controls, and dense transcript or history content legible before adding decorative elements.
- The sidebar uses the existing LearnFlux leaf mark and the approved meadow artwork as a low-contrast footer illustration. The reading shelf uses the existing reading-nook artwork as a subdued header surface.
- Do not add a global search, profile, or sample records unless there is real behavior and data behind them.
- The standalone visual-learning navigation item remains omitted. The in-context “图解” tab in study content remains available.
- The single-study result detail page uses the same paper, leaf-green, and sage surfaces while preserving its existing transcript, summary, export, Obsidian, and in-context diagram controls.
- The focus-writing page keeps its original animated rain and snow scenes and ambient audio. Workbench styles recolor its controls and translucent writing card without dimming or replacing the scene canvas.

## Do's and Don'ts

### Do

- Keep only the brand copy, landscape, preview, and three-step strip in the landing page's main composition.
- Use specific copy to distinguish video transcripts from document and text reading.
- Keep local use and the current product state clear.

### Don't

- Don't imply that the illustrative preview is an interactive player.
- Don't add public launch, pricing, customer, or licensing claims without a confirmed decision.
- Don't add decorative controls that have no working interaction.
