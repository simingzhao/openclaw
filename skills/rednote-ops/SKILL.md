---
name: rednote-ops
description: >
  小红书平台操作 CLI — 发布图文/视频、搜索、推荐流、帖子详情、点赞、收藏、评论、回复评论、用户主页、定时发布、从草稿发布。
  基于 xiaohongshu-mcp。Use when interacting with RedNote/Xiaohongshu for publishing, searching,
  browsing feeds, engaging (like/favorite/comment/reply), or pulling post/user data.
metadata:
  openclaw:
    emoji: "📕"
    requires:
      bins: ["python3"]
---

# RedNote Ops（小红书操作）

所有与小红书平台的交互：发布、搜索、互动、数据。

## Setup

```bash
SKILL_DIR="{baseDir}"
# 复用已有 venv 或创建
python3 -m venv "$SKILL_DIR/.venv" 2>/dev/null
"$SKILL_DIR/.venv/bin/pip" install requests
```

MCP 服务 `xiaohongshu-mcp` 须在 `localhost:18060` 运行。

## Usage

```bash
VENV="{baseDir}/.venv/bin/python3"
OPS="{baseDir}/scripts/rednote_ops.py"
```

### 账号

```bash
$VENV "$OPS" status          # 检查登录
$VENV "$OPS" qrcode          # 获取登录二维码
$VENV "$OPS" logout          # 清除cookies
```

### 发布

```bash
# 图文
$VENV "$OPS" publish --title "标题" --content "正文" --images a.png b.png --tags AI 科技

# 视频
$VENV "$OPS" publish-video --title "标题" --content "正文" --video video.mp4 --tags AI

# 从草稿（content.json）发布
$VENV "$OPS" publish-draft --draft /path/to/content.json

# 定时发布（任何发布命令加 --schedule）
$VENV "$OPS" publish --title "xx" --content "xx" --images a.png --schedule "2026-02-26T10:00:00+08:00"
```

### 搜索 / 浏览

```bash
# 搜索
$VENV "$OPS" search "AI赚钱"
$VENV "$OPS" search "Vibe Coding" --sort 最多点赞 --time 一周内 --note-type 图文

# 推荐流
$VENV "$OPS" feeds

# 帖子详情（含评论）
$VENV "$OPS" detail FEED_ID XSEC_TOKEN
$VENV "$OPS" detail FEED_ID XSEC_TOKEN --all-comments --limit 50 --with-replies

# 用户主页
$VENV "$OPS" profile USER_ID XSEC_TOKEN
```

### 互动

```bash
# 点赞 / 取消点赞
$VENV "$OPS" like FEED_ID XSEC_TOKEN
$VENV "$OPS" like FEED_ID XSEC_TOKEN --undo

# 收藏 / 取消收藏
$VENV "$OPS" favorite FEED_ID XSEC_TOKEN
$VENV "$OPS" favorite FEED_ID XSEC_TOKEN --undo

# 评论
$VENV "$OPS" comment FEED_ID XSEC_TOKEN "好文收藏了！"

# 回复评论
$VENV "$OPS" reply FEED_ID XSEC_TOKEN "谢谢！" --comment-id CID --user-id UID
```

## 草稿发布（publish-draft）

读取 `content.json`（rednote-writer / batch_gen 的产出），自动提取标题、正文、标签、图片路径并发布。

图片查找优先级：

1. `card_paths` 字段
2. `images` 字段
3. `image_paths` 字段
4. **自动扫描** content.json 同目录下的 `*.png` / `*.jpg` / `*.jpeg`（按文件名排序）

其他自动行为：

- `cta_question` 字段会自动拼接到正文末尾（如果正文中尚未包含）
- 不存在的图片路径会被跳过并警告
- 相对路径基于 content.json 所在目录解析

```json
{
  "post_title": "标题",
  "post_body": "正文",
  "tags": ["AI", "科技"],
  "cta_question": "你觉得呢？评论区聊聊👇"
}
```

图片放在 content.json 同目录即可，无需手动指定路径。

## 搜索 filters

| 参数          | 选项                                         |
| ------------- | -------------------------------------------- |
| `--sort`      | 综合 / 最新 / 最多点赞 / 最多评论 / 最多收藏 |
| `--time`      | 不限 / 一天内 / 一周内 / 半年内              |
| `--note-type` | 不限 / 视频 / 图文                           |

## 平台限制

- 标题 ≤ 20字（超长自动截断）
- 正文 ≤ 950字（留余量给tags拼接）
- 图文至少1张图
- 定时发布：1小时 ~ 14天内
- 所有操作需已登录（`status` 检查）

## 环境变量

| 变量              | 说明         | 默认                         |
| ----------------- | ------------ | ---------------------------- |
| `REDNOTE_MCP_URL` | MCP 服务地址 | `http://localhost:18060/mcp` |
