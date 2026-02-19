# 选题生成Prompt

基于以下Scout情报，生成{count}个微信公众号文章选题建议。

## Scout情报

### X/Twitter热点

{tweets}

### 视频摘要

{videos}

### 博客文章

{articles}

### 情报报告

{reports}

## 选题标准

1. **热度**：话题是否有足够关注度？推文互动量、讨论量
2. **素材支撑**：Scout素材是否足够支撑一篇完整文章？
3. **独特角度**：能否找到与众不同的切入点？
4. **实用价值**：对读者有什么实际帮助？
5. **时效性**：是否需要尽快发布？

## 输出格式（JSON）

```json
{
  "topics": [
    {
      "id": 1,
      "title": "文章标题（吸引人、不标题党）",
      "angle": "独特切入角度",
      "heat": "🔥🔥🔥（1-3个火）",
      "scout_support": {
        "tweets": "数量",
        "videos": "数量",
        "articles": "数量"
      },
      "key_sources": ["可引用的关键来源"],
      "why_good": "为什么这个选题值得写",
      "urgency": "high/medium/low（时效性）"
    }
  ]
}
```
