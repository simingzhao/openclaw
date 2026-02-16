---
name: scout-x
description: Scout's X/Twitter patrol skill. Searches keywords, fetches posts from tracked accounts, discovers new voices. Uses x-api under the hood with smart scheduling to minimize API costs.
---

# Scout X Patrol

Scout专用的X巡逻skill。智能调度搜索，最小化API成本。

## 依赖

- `x-api` skill（必须已配置好OAuth credentials）
- 使用x-api的venv（已包含PyYAML）

## 配置文件

配置存放在Scout workspace:

```
/Users/simingzhao/.openclaw/workspace-scout/sources/x-watchlist.yaml
```

## 使用

```bash
VENV="/Users/simingzhao/Desktop/openclaw/skills/x-api/.venv/bin/python3"
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/scout-x"
SCOUT_X="$VENV $SKILL_DIR/scripts/scout_x.py"

# 运行巡逻（自动轮询关键词和账号）
$SCOUT_X patrol

# 只搜索关键词
$SCOUT_X keywords

# 只查看追踪账号
$SCOUT_X accounts

# 获取trending
$SCOUT_X trending

# 查看配置状态
$SCOUT_X status

# 添加新关键词
$SCOUT_X add-keyword "MCP protocol" --tier trending

# 添加新账号
$SCOUT_X add-account "anthropic" --tier tier1

# 强制搜索特定关键词（不计入轮询）
$SCOUT_X search "specific query"
```

## 巡逻策略

为了控制API成本，采用轮询策略：

1. **关键词轮询**：每次只搜索部分关键词
   - `core` 关键词每次都搜
   - `trending` 关键词轮流搜
2. **账号轮询**：每次只查部分账号
   - `tier1` 账号每次都查
   - `tier2` 和 `discovered` 账号轮流查

3. **去重**：记录已处理的post ID，避免重复保存

## 输出

结果保存到:

```
/Users/simingzhao/.openclaw/workspace-scout/raw/x-posts/YYYY-MM-DD_patrol.md
```

## 自动发现

当发现高互动的新账号时，会自动加入 `discovered` 列表。判断标准：

- 被多个tier1账号互动
- 帖子获得高engagement（likes > 1000 或 retweets > 200）
