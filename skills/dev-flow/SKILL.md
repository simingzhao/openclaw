---
name: dev-flow
description: End-to-end coding workflow — plan, build (Codex CLI), test, push to GitHub, deploy to Vercel. Use when the user asks to build an app, create a project, code something, deploy to Vercel, or any coding task that involves planning + implementation + deployment.
---

# Dev Flow

Full coding workflow: Plan → Code (Codex) → Test → GitHub Push → Vercel Deploy.

## Prerequisites

- `codex` CLI (coding agent)
- `gh` CLI (GitHub, authenticated)
- `git`
- `ffmpeg`, `node`, `pnpm`/`npm` (for testing)
- Deploy script: `scripts/deploy.sh` (relative to this skill directory)

## Workflow

### Phase 1: Plan (with user)

Discuss requirements with user. Produce a clear plan document:

```markdown
## Project: [name]

- **Goal**: what we're building
- **Stack**: framework, key libs
- **Features**: bullet list
- **Repo**: new or existing (github.com/simingzhao/[repo])
```

Iterate until user approves. Save plan to `/tmp/dev-plan.md`.

### Phase 2: Code (Codex CLI)

**New project:**

```bash
# Create project dir
mkdir -p ~/Projects/[project-name] && cd ~/Projects/[project-name]
git init

# Run Codex with the plan
codex exec --full-auto "Build this project based on the following plan: $(cat /tmp/dev-plan.md)"
```

**Existing project:**

```bash
cd ~/Projects/[project-name]
codex exec --full-auto "Modify the project: [description of changes]"
```

Always use `pty:true` and `workdir` when running Codex:

```
exec pty:true workdir:~/Projects/[project-name] command:"codex exec --full-auto 'prompt'"
```

For long tasks, use `background:true` and monitor with `process action:log`.

### Phase 3: Test

After Codex completes:

```bash
cd ~/Projects/[project-name]

# Install deps
pnpm install  # or npm install

# Run dev server to verify
pnpm dev &
# Check if it builds
pnpm build
```

If tests fail, send errors back to Codex for fixing.

### Phase 4: Push to GitHub

**New repo:**

```bash
cd ~/Projects/[project-name]
git add -A
git commit -m "feat: initial commit - [description]"
gh repo create simingzhao/[project-name] --public --source=. --push
```

**Existing repo (new changes):**

```bash
cd ~/Projects/[project-name]
git add -A
git commit -m "feat: [description of changes]"
git push origin main
```

Use conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.

### Phase 5: Deploy to Vercel

```bash
# Preview deploy
bash [skill-dir]/scripts/deploy.sh ~/Projects/[project-name]

# Production deploy
bash [skill-dir]/scripts/deploy.sh ~/Projects/[project-name] --prod
```

Uses `vercel` CLI (already authenticated as simingzhaous-1945).
Auto-installs deps, builds, deploys. Returns URL.

If deploy fails with network/sandbox issues, retry with `elevated:true`.

Output format:

```
✓ Deployment successful!
URL: https://project-abc123.vercel.app
Mode: Preview
```

Present URL to user. Ask if they want to promote to production.

## Quick Reference

| Phase  | Tool      | Key Command                       |
| ------ | --------- | --------------------------------- |
| Plan   | Chat      | Iterate with user                 |
| Code   | Codex CLI | `codex exec --full-auto "prompt"` |
| Test   | pnpm/npm  | `pnpm build`                      |
| Push   | gh + git  | `gh repo create` / `git push`     |
| Deploy | deploy.sh | `bash scripts/deploy.sh [path]`   |

## Notes

- Always use Codex for coding — never write code yourself.
- Plan first, code second. Don't skip the planning phase.
- If Codex fails or gets stuck, re-prompt with more specific instructions.
- For complex projects, break into multiple Codex runs.
- Keep user informed at each phase transition.
- GitHub account: `simingzhao`
