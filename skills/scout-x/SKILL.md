---
name: scout-x
description: Scout's X/Twitter patrol skill. Searches keywords, fetches posts from tracked accounts, discovers new voices. Uses x-api under the hood with smart scheduling to minimize API costs.
---

# Scout X Patrol

Scout专用的X巡逻skill。智能调度搜索，最小化API成本，自维护watchlist。

## 依赖

- `x-api` skill（必须已配置好OAuth credentials）

## 文件

| 文件                               | 作用                       | 谁维护                     |
| ---------------------------------- | -------------------------- | -------------------------- |
| `sources/x-watchlist.yaml`         | 追踪列表配置               | Scout自维护 + 人工override |
| `sources/x-patrol-state.json`      | 轮询状态、seen posts       | 自动                       |
| `sources/x-watchlist-metrics.json` | 质量指标（命中率、互动量） | 自动                       |
| `raw/x-posts/YYYY-MM-DD_*.md`      | 巡逻结果                   | 自动                       |

## 使用

```bash
VENV="/Users/simingzhao/Desktop/openclaw/skills/x-api/.venv/bin/python3"
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/scout-x"
SCOUT_X="$VENV $SKILL_DIR/scripts/scout_x.py"

# ── 巡逻 ──
$SCOUT_X patrol                # 完整巡逻（关键词+账号轮询）
$SCOUT_X patrol --json         # 巡逻 + JSON摘要
$SCOUT_X keywords --all        # 搜ALL关键词
$SCOUT_X accounts --all        # 查ALL账号
$SCOUT_X search "query"        # 即时搜索（不影响状态）

# ── 自维护 ──
$SCOUT_X maintain              # 分析质量，生成建议
$SCOUT_X maintain --apply      # 分析+自动清理沉默账号
$SCOUT_X maintain --json       # 输出JSON报告供agent决策
$SCOUT_X health                # 快速健康检查（JSON）

# ── 管理 ──
$SCOUT_X status
$SCOUT_X add-keyword "MCP protocol" --tier trending
$SCOUT_X add-account "anthropic" --tier tier2_tools
$SCOUT_X remove-keyword "old topic"
$SCOUT_X remove-account "inactive"
```

## 自维护机制

### 数据流

每次 `patrol` 自动积累指标：

- **账号指标**：命中率（有新内容 vs 没有）、平均互动量、最后活跃时间
- **关键词指标**：平均结果数、平均互动量

### `maintain` 做什么

1. **识别沉默账号** — 连续5次miss、命中率<20% → 建议删除
2. **识别低质账号** — 平均互动<10 → 建议降级
3. **识别高质账号** — 平均互动>500的tier2 → 建议升tier1
4. **识别低效关键词** — 平均结果<1 → 建议删除
5. **解析discovered IDs** — 把user ID转为username（每次最多5个）
6. `--apply` 自动清理confirmed dead accounts（不动tier1）

### Scout日常维护流程

**每次patrol后**（自动）：

- 指标自动更新到 `x-watchlist-metrics.json`

**每1天一次**（在heartbeat或手动触发）：

1. 运行 `maintain --apply --json`
2. 根据JSON报告决定：
   - 要不要升级某些tier2到tier1
   - 要不要删掉低效关键词
   - 要不要加新关键词（基于近期趋势）
3. 用 `add-keyword` / `add-account` / `remove-*` 执行

**收到重大事件时**（主动）：

- 新模型发布 → 加相关关键词
- 新公司/人物崛起 → 加到对应tier2组
- 某人转行/不再相关 → remove

### `health` 快速检查

输出JSON，适合heartbeat调用：

```json
{
  "total_accounts": 86,
  "data_coverage": 0.75,
  "avg_engagement": 245,
  "unresolved_ids": 3,
  "needs_maintain": true
}
```

## 巡逻策略

### 关键词轮询

- `core` 每次都搜 + `trending` 轮流搜
- 自动加 `-is:retweet lang:en`
- 自动应用 `filters.exclude_keywords`

### 账号轮询

- `tier1` 每次都查 + 所有 `tier2_*` 合并轮流查
- 排除 replies 和 retweets
- 支持任意 `tier2_xxx` 子组名

### 去重 & 过滤

- 保留最近500个post ID去重
- `filters.exclude_keywords` 排除crypto等噪音

### 自动发现

- 高互动帖子的新作者 → discovered
- `maintain` 把 user ID 解析为 username
