---
name: wechat-writer
description: 高质量微信公众号文章写作pipeline。基于Scout情报，6阶段流程：选题→计划→调研→写作→审核→去AI化。输出authentic、有观点的内容。
homepage: https://github.com/anthropics/anthropic-cookbook
metadata:
  openclaw:
    emoji: "✍️"
    requires:
      bins: ["python3"]
      env: ["GEMINI_API_KEY"]
    primaryEnv: "GEMINI_API_KEY"
---

# WeChat Writer

高质量微信公众号文章写作pipeline。

**核心理念**：质量是生命线。不是"用AI写文章"，是"用AI辅助写出好文章"。

## 7阶段Pipeline

```
TOPICS → PLAN → RESEARCH → WRITE → REVIEW → DE-AI → COVER
  ↓        ↓        ↓         ↓        ↓        ↓       ↓
选题建议   框架    补充调研   初稿    质检    去AI化   封面图
(需approve)                                   ↓       ↓
                                           final.md  cover.png
                                                     cover_prompt.txt
```

## Setup

```bash
# 需要 google-genai SDK
pip install google-genai

# 设置 GEMINI_API_KEY
export GEMINI_API_KEY="your-key"
```

## Usage

### 1. 初始化文章 + 生成选题

```bash
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/wechat-writer"
WRITER="$SKILL_DIR/scripts/wechat_writer.py"

# 扫描Scout，生成选题建议
python3 "$WRITER" init \
  --scout-workspace ~/.openclaw/workspace-scout \
  --date-range 3d \
  --output ~/articles/wechat-blog/2026-02-17_draft/
```

输出：

- `source_pack.json` — Scout素材打包
- `topics.json` — 选题建议（3-5个）

### 2. 选定主题，执行完整pipeline

```bash
python3 "$WRITER" run \
  --workdir ~/articles/wechat-blog/2026-02-17_kimi-claw/ \
  --topic "Kimi Claw发布分析"
```

自动执行：PLAN → RESEARCH → WRITE → REVIEW → DE-AI → COVER

输出：

- `plan.json` — 文章框架
- `research.json` — 补充调研
- `draft.md` — 初稿
- `review.json` — 质检结果
- `final.md` — 定稿（去AI化后）
- `cover_prompt.txt` — 封面图 prompt（优化过的 Nano Banana Pro prompt）
- `cover_data.json` — 封面图创意数据
- `cover.png` — 封面图（900×383px，自动裁剪）

### 3. 同步到iCloud Obsidian

pipeline完成后自动同步到：

```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Articles/
```

### 分步执行（调试用）

```bash
# 单独执行某个阶段
python3 "$WRITER" plan --workdir ./article/ --topic "xxx"
python3 "$WRITER" research --workdir ./article/
python3 "$WRITER" write --workdir ./article/
python3 "$WRITER" review --workdir ./article/
python3 "$WRITER" deai --workdir ./article/
python3 "$WRITER" cover --workdir ./article/  # 基于 final.md 生成封面图
```

### 语气/风格微调（写完之后调整）

```bash
# 调整 final.md 的语气，不改变观点和内容
python3 "$WRITER" tone-adjust \
  --workdir ./article/ \
  --instruction "语气柔和一些，不要太刻薄，像朋友分享而不是在批评"

# 调整后同步到 iCloud Obsidian
python3 "$WRITER" tone-adjust \
  --workdir ./article/ \
  --instruction "结尾更有力量感，加一点鼓励的话" \
  --sync
```

**特点：**

- 全程文件交换，不传大文本给 shell，不超时
- 自动备份原文到 `final_before_tone_adjust.md`
- 支持任意自然语言改写指令

## 模型配置

| 阶段     | 模型                             | Thinking | Grounding        |
| -------- | -------------------------------- | -------- | ---------------- |
| TOPICS   | gemini-3-flash                   | off      | ❌               |
| PLAN     | gemini-3-flash                   | off      | ❌               |
| RESEARCH | gemini-3-flash                   | off      | ✅ Google Search |
| WRITE    | gemini-3-flash                   | off      | ❌               |
| REVIEW   | gemini-3-flash                   | off      | ❌               |
| DE-AI    | gemini-3-flash                   | off      | ❌               |
| COVER    | gemini-3-flash → nano-banana-pro | off      | ❌               |

COVER 阶段分两步：先用 Gemini 生成优化的封面 prompt，再用 Nano Banana Pro 生成图片（fallback: gemini-3-pro-image → gemini-2.5-flash-image）。

## Persona配置

编辑 `personas/default.yaml` 定义公众号风格：

```yaml
name: "思明的AI观察"
tone: "务实、有态度、偶尔调皮"
avoid:
  - "首先...其次...最后..."
  - "值得注意的是"
  - "综上所述"
prefer:
  - 直接给结论
  - 敢下判断
  - 适当吐槽
```

## 文件结构

```
skills/wechat-writer/
├── SKILL.md
├── scripts/
│   ├── wechat_writer.py      # 主脚本
│   └── prompts/
│       ├── topics.md         # 选题prompt
│       ├── plan.md           # 框架prompt
│       ├── research.md       # 调研prompt
│       ├── write.md          # 写作prompt
│       ├── review.md         # 审核prompt
│       ├── deai.md           # 去AI化prompt
│       └── cover.md          # 封面图prompt生成
├── personas/
│   └── default.yaml          # 公众号人设
└── examples/
    └── ...
```

## Scout素材整合

init阶段扫描Scout workspace，打包相关素材：

- `reports/` — 情报简报
- `raw/x-posts/` — X/Twitter热点
- `raw/youtube/` — 视频摘要
- `raw/articles/` — 博客文章
- `notes/` — Scout分析笔记

素材打包进 `source_pack.json`，贯穿整个pipeline。

## 输出示例

见 `examples/` 目录。
