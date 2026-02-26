---
name: rednote-writer
description: 小红书内容写作与卡片生成技能。从巡逻素材生成文案、渲染卡片并保存到 drafts；发布由 rednote-ops 负责。
metadata:
  openclaw:
    emoji: "📕"
    requires:
      bins: ["python3"]
      env: ["GEMINI_API_KEY"]
    primaryEnv: "GEMINI_API_KEY"
---

# Rednote Writer（写作与制图）

本技能只负责：素材整理 -> 文案生成 -> 卡片渲染 -> 草稿保存 -> iCloud 同步。

发布请使用独立技能 `rednote-ops`。

## 架构

```text
巡逻素材 (X digest + YouTube summaries)
    ↓
content_gen.py  — Gemini 多类型内容生成（brief/analysis/opinion/tools）
    ↓ content.json
card_gen.py     — Pillow 多风格卡片渲染（typography-card/notes-app/text-only）
    ↓ PNG
rednote_writer.py — Pipeline 编排 + drafts 存储 + iCloud同步
```

## Setup

```bash
SKILL_DIR="{baseDir}"
VENV="$SKILL_DIR/.venv/bin/python3"

# 首次安装
python3 -m venv "$SKILL_DIR/.venv"
$SKILL_DIR/.venv/bin/pip install Pillow google-genai requests
```

## CLI

### 1. Pipeline（推荐）

```bash
VENV="{baseDir}/.venv/bin/python3"
WRITER="{baseDir}/scripts/rednote_writer.py"

# 自动素材 -> 生成文案 -> 生成卡片 -> 保存 drafts -> iCloud
$VENV "$WRITER" daily-brief --source both --style typography-card --type brief

# 指定来源
$VENV "$WRITER" daily-brief --source x --style notes-app --type analysis
$VENV "$WRITER" daily-brief --source youtube --style text-only --type opinion

# 指定素材与日期
$VENV "$WRITER" daily-brief -i /path/to/digest.md -d 02.25 --style typography-card --type tools

# 从已有 content.json 重新渲染卡片并保存
$VENV "$WRITER" from-json -i content.json --style notes-app --type analysis
```

参数说明：

- `--style`: `typography-card` | `notes-app` | `text-only`
- `--type`: `brief` | `analysis` | `opinion` | `tools`

### 2. 仅生成文案

```bash
CONTENT="{baseDir}/scripts/content_gen.py"

$VENV "$CONTENT" auto --source both --type brief -o content.json
$VENV "$CONTENT" from-file -i digest.md -d 02.25 --type analysis -o content.json
$VENV "$CONTENT" from-file -i digest.md --type opinion -o content.json
$VENV "$CONTENT" from-file -i digest.md --type tools -o content.json
```

### 3. 仅生成卡片

```bash
CARD="{baseDir}/scripts/card_gen.py"

# 批量
$VENV "$CARD" batch -i content.json -o ./cards --style typography-card

# 单张
$VENV "$CARD" card --style notes-app -t "标题" -b "内容" -o card.png

# 仅封面
$VENV "$CARD" cover --style text-only -t "标题" -s "副标题" -o cover.png
```

## 输出目录

Pipeline 输出到：

```text
~/.openclaw/workspace-rednote-ops/content/drafts/
└── {date}_{slug}/
    ├── content.json
    ├── content.txt
    ├── meta.json
    └── cards/
        ├── 00_cover.png
        ├── 01.png ...
```

`meta.json` 字段：

- `style_id`
- `content_type`
- `created_at`
- `card_count`

iCloud 同步目录：

```text
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Rednote/
```

## 卡片约束

- 渲染引擎：Pillow only（无任何图像 API 调用）
- 尺寸：1080x1440（3:4）
- 字体：
  - `/System/Library/Fonts/STHeiti Medium.ttc`
  - `/System/Library/Fonts/STHeiti Light.ttc`
- 首图固定为封面：`00_cover.png`
