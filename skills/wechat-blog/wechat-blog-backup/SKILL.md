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

### 上传素材

```bash
# 上传封面图（永久素材，返回 media_id）
$WX upload-cover /path/to/cover.jpg

# 上传正文图片（返回 URL，用于文章内 <img> 标签）
$WX upload-image /path/to/image.jpg
```

### 草稿管理

```bash
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

### 发布一篇新文章

1. 上传封面图获取 `thumb_media_id`
2. 上传正文图片获取 URL（如有）
3. 创建草稿
4. 发布草稿
5. 查询发布状态确认成功
