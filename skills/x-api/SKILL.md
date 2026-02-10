---
name: x-api
description: Interact with X (Twitter) via the official X API v2. Use for searching posts, fetching trending topics, reading post content and engagement stats, publishing posts, replying/commenting on posts, liking, reposting, following users, and managing your X account programmatically.
---

# X API

Interact with your X (Twitter) account via the X API v2. Supports searching posts, trending topics, post stats, publishing, replying, liking, reposting, and following.

## Setup

```bash
# Create virtual environment and install dependencies
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/x-api"
python3 -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/pip" install requests requests-oauthlib
```

### Required Environment Variables

The script reads four OAuth 1.0a credentials from the environment: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`. These are sourced from `~/.zshrc`.

## Usage

```bash
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/x-api"
XA="$SKILL_DIR/.venv/bin/python3 $SKILL_DIR/scripts/x_api.py"

# All commands accept --human for human-readable output (default is JSON)
```

## Commands

### Get Authenticated User

```bash
$XA me
$XA --human me
```

### Search Posts

```bash
# Basic search
$XA search "artificial intelligence"

# With options
$XA search "from:elonmusk" --max-results 20 --sort-order recency
$XA --human search "#AI lang:en -is:retweet" --max-results 25

# Search operators: from:, to:, has:media, has:links, is:retweet, -is:retweet, lang:, #hashtag, @mention
```

### Trending Topics

```bash
# Worldwide trends
$XA trending 1

# US trends
$XA trending 23424977

# With max trends
$XA --human trending 23424977 --max-trends 10
```

### Fetch Post Content and Stats

```bash
# Get a post by ID (includes public_metrics: likes, reposts, replies, views, bookmarks)
$XA get-post 1346889436626259968
$XA --human get-post 1346889436626259968
```

### Look Up User

```bash
$XA get-user elonmusk
$XA --human get-user @TwitterDev
```

### Get User's Posts

```bash
# Recent posts from a user
$XA user-posts elonmusk --max-results 20

# Exclude replies and retweets
$XA --human user-posts TwitterDev --exclude replies retweets
```

### Publish a Post

```bash
$XA post "Hello from the X API!"
$XA --human post "Exploring the X API v2 endpoints"
```

### Reply to a Post

```bash
$XA reply 1346889436626259968 "Great post! Thanks for sharing."
$XA --human reply 1346889436626259968 "Interesting thread"
```

### Like a Post

```bash
$XA like 1346889436626259968
```

### Repost (Retweet)

```bash
$XA repost 1346889436626259968
```

### Follow a User

```bash
$XA follow elonmusk
$XA follow @TwitterDev
```

### Delete a Post

```bash
$XA delete 1346889436626259968
```

## Common WOEIDs for Trending

| WOEID    | Location       |
| -------- | -------------- |
| 1        | Worldwide      |
| 23424977 | United States  |
| 23424975 | United Kingdom |
| 23424856 | Japan          |
| 23424829 | Germany        |
| 23424819 | France         |
| 23424848 | India          |
| 23424900 | Mexico         |
| 23424950 | Sweden         |
| 23424868 | South Korea    |
| 23424803 | Canada         |
| 23424768 | Brazil         |
| 23424782 | Australia      |

## Output

- Default output is **JSON** (pipe to `jq` for filtering)
- Use `--human` flag for human-readable summaries
- Errors are printed to stderr with non-zero exit codes

## Notes

- OAuth 1.0a authentication supports both read and write operations
- The `search` command uses the Recent Search endpoint (last 7 days)
- Write operations (`post`, `reply`, `like`, `repost`, `follow`) automatically fetch your user ID via `/2/users/me`
- X search query operators: `from:user`, `to:user`, `has:media`, `has:links`, `is:retweet`, `-is:retweet`, `lang:en`, `#hashtag`, `@mention`
