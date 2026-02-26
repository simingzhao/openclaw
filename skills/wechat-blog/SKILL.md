---
name: wechat-blog
description: 微信公众号管理与运营。用于创建草稿、上传素材、发布文章、管理公众号内容。支持：(1) 上传封面图/正文图片 (2) 创建/更新/删除草稿 (3) 发布文章 (4) 查询文章列表。当用户需要发布微信公众号文章、管理公众号内容、创建草稿时使用此 skill。
---

# 微信公众号管理

管理微信公众号的草稿、素材和文章发布。

## 配置

环境变量（在 `~/.zshrc` 中配置）：

```bash
export WECHAT_APPID="你的AppID"
export WECHAT_APPSECRET="你的AppSecret"
```

## 使用方法

```bash
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/wechat-blog"
WX="$SKILL_DIR/.venv/bin/python3 $SKILL_DIR/scripts/wechat_api.py"
```

### 查看 Token 状态

```bash
$WX token
```

### Markdown → 微信 HTML 转换

```bash
# 将 Markdown 转换为微信排版 HTML（内联CSS，自动提取标题）
$WX md2html article.md -o article.html

# 直接打印到 stdout
$WX md2html article.md
```

支持的 Markdown 元素：

- `##` / `###` 标题（带蓝色边框/分隔线）
- `**粗体**` / `*斜体*` / `` `行内代码` ``
- 无序列表 / 有序列表
- `> 引用块`（带背景色）
- 代码块（深色主题）
- `---` 分割线

### 生成封面图（Gemini AI）

```bash
# 用 AI 生成封面图，自动裁剪到 900×383px（公众号推荐比例 2.35:1）
$WX gen-cover "AI超级个体、科技感、未来城市" -o cover.png

# 需要 GEMINI_API_KEY 环境变量
```

### 上传素材

```bash
# 上传封面图（永久素材，返回 media_id）
$WX upload-cover /path/to/cover.jpg

# 上传正文图片（返回 URL，用于文章内 <img> 标签）
$WX upload-image /path/to/image.jpg
```

### 草稿管理

```bash
# 创建草稿（从 Markdown 文件，自动转换排版）⭐️ 推荐
$WX draft-add --from-md article.md --thumb-media-id "封面图media_id"

# 创建草稿（从 JSON 文件）
$WX draft-add /path/to/article.json

# 创建草稿（命令行参数）
$WX draft-add --title "文章标题" --content "<p>正文HTML</p>" --thumb-media-id "封面图media_id"

# 查看草稿列表
$WX draft-list

# 获取草稿详情
$WX draft-get <media_id>

# 更新草稿
$WX draft-update <media_id> --title "新标题"

# 删除草稿
$WX draft-delete <media_id>
```

### 发布文章

```bash
# 发布草稿（返回 publish_id）
$WX publish <media_id>

# 查询发布状态
$WX publish-status <publish_id>

# 获取已发布文章列表
$WX article-list
```

## 文章 JSON 格式

```json
{
  "title": "文章标题",
  "author": "作者（可选）",
  "digest": "摘要（可选，自动截取前54字）",
  "content": "<p>正文 HTML 内容</p>",
  "thumb_media_id": "封面图 media_id",
  "need_open_comment": 0,
  "only_fans_can_comment": 0
}
```

## 注意事项

1. **IP 白名单**：需要在公众号后台配置服务器 IP
2. **Token 有效期**：2 小时，脚本自动缓存和刷新
3. **图片限制**：封面图/正文图片仅支持 jpg/png，<1MB
4. **API 发布的文章**：不会触发微信推荐，不会显示在历史消息中，只能通过链接访问
5. **永久素材上限**：100,000 张

## 常见工作流

### 发布一篇新文章（推荐流程）

```bash
# 1. AI 生成封面图（自动 900×383px）
$WX gen-cover "文章主题关键词" -o cover.png

# 2. 上传封面图
THUMB_ID=$($WX upload-cover cover.png | python3 -c "import json,sys; print(json.load(sys.stdin)['media_id'])")

# 3. 从 Markdown 创建草稿（自动转换排版）
DRAFT_ID=$($WX draft-add --from-md final.md --thumb-media-id "$THUMB_ID" --author "思明" | python3 -c "import json,sys; print(json.load(sys.stdin)['media_id'])")

# 4. 在公众号后台预览后手动群发（订阅号）
echo "草稿已创建: $DRAFT_ID，前往草稿箱发布"
```
