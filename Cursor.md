# Cursor IDE Guide

How this project is configured for [Cursor](https://cursor.com) — skills, agent rules, MCP servers, and day-to-day workflows.

All project skills live in **one place**: `.agents/skills/`.

---

## Folder structure

```
autogen/
├── .cursor/
│   └── settings.json          # Registers skills from .agents/skills/
├── .agents/skills/            # Single source of truth for all project skills
│   ├── docs-router/
│   ├── fallow/
│   └── frontend-design/
├── skills-lock.json           # Lockfile for externally installed skills
├── .mcp.json                  # MCP server configuration
└── Makefile                   # Common dev commands
```

Each skill is a directory with a required `SKILL.md`:

```
.agents/skills/my-skill/
├── SKILL.md              # Required — YAML frontmatter + instructions
├── reference.md          # Optional
└── scripts/              # Optional
```

---

## Configuration

### `.cursor/settings.json`

Registers skills from `.agents/skills/` into Cursor agent context:

```json
{
  "customRules": [
    {
      "name": "docs-router",
      "path": "../.agents/skills/docs-router/SKILL.md",
      "description": "Route documentation to README.md (inline) or separate files linked from README.md. Use when asked to create, write, or generate documentation, READMEs, guides, API references, setup instructions, changelogs, architecture docs, tutorials, or any project Markdown content."
    },
    {
      "name": "fallow",
      "path": "../.agents/skills/fallow/SKILL.md",
      "description": "Codebase intelligence for JavaScript and TypeScript. Reports quality, changed-code risk, cleanup opportunities (unused files, exports, types, dependencies), code duplication, circular dependencies, complexity hotspots, architecture boundary violations, feature flag patterns, and security candidates. Use when asked to analyze code health, audit PR risk, find unused code, detect duplicates, check circular dependencies, audit complexity, clean up the codebase, auto-fix issues, or run fallow."
    },
    {
      "name": "frontend-design",
      "path": "../.agents/skills/frontend-design/SKILL.md",
      "description": "Create distinctive, production-grade frontend interfaces with high design quality. Use when asked to build web components, pages, landing pages, dashboards, React components, HTML/CSS layouts, or when styling or beautifying any web UI. Generates creative, polished code that avoids generic AI aesthetics."
    }
  ]
}
```

Paths are relative to `.cursor/settings.json`. Add a new entry for each skill you want Cursor to always load.

### `skills-lock.json`

Tracks externally installed skills from GitHub. Commit this file so the team gets the same skills.

| Skill | Source |
|-------|--------|
| `fallow` | [fallow-rs/fallow-skills](https://github.com/fallow-rs/fallow-skills) |
| `frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) |

Install or update skills:

```bash
npx skills find <query>          # search skills.sh
npx skills add <owner/repo@skill> -y
npx skills update
```

---

## Installed skills

### docs-router (project custom)

Ensures documentation either lives in `README.md` or in a separate file linked from it.

- **Path:** `.agents/skills/docs-router/SKILL.md`
- **Registered in:** `.cursor/settings.json`, `.claude/settings.json`
- **Triggers:** "create documentation", "write docs", "document this", etc.

### fallow (external)

Codebase intelligence for JavaScript/TypeScript — quality audits, unused code, circular deps, complexity.

- **Path:** `.agents/skills/fallow/`
- **Also installed in:** `frontend/.agents/skills/fallow/`

### frontend-design (external)

Production-grade UI design guidance — distinctive aesthetics, avoids generic AI styling.

- **Path:** `.agents/skills/frontend-design/`

---

## MCP servers

Configured in `.mcp.json`:

| Server | Purpose | Auth |
|--------|---------|------|
| `github` | PRs, issues, workflows | `GITHUB_TOKEN` env var |

Set your token before using GitHub MCP:

```bash
export GITHUB_TOKEN=ghp_...
```

---

## Creating a new skill

All skills go in `.agents/skills/<name>/SKILL.md`.

### Option A — Install from the ecosystem

```bash
npx skills add <owner/repo@skill> -y
```

Skill lands in `.agents/skills/<name>/` and `skills-lock.json` is updated.

### Option B — Create manually

1. Create the directory and `SKILL.md`:

```markdown
---
name: my-skill
description: What it does. Use when the user asks to X or Y.
---

# My Skill

## When to Use
- Trigger phrase one
- Trigger phrase two

## Instructions
1. Step one
2. Step two
```

2. Register in `.cursor/settings.json`:

```json
{
  "name": "my-skill",
  "path": "../.agents/skills/my-skill/SKILL.md",
  "description": "One-line summary with trigger terms"
}
```

3. Register in `.claude/settings.json` under `customSkills` (with `triggers` array).
4. Add a link in `README.md` under **Claude Code Skills & Tools**.

### Skill authoring tips

| Do | Don't |
|----|-------|
| Write descriptions in third person with trigger terms | Use vague names like `helper` or `utils` |
| Keep `SKILL.md` under 500 lines | Store skills outside `.agents/skills/` |
| Link reference files one level deep | Use Windows-style paths (`scripts\foo.py`) |
| Include concrete examples | Add time-sensitive instructions |

---

## Working in this project

### Start services

```bash
make up          # start all containers
make dev         # dev overrides
make logs        # follow all logs
make logs-backend
```

### Database

```bash
make migrate
make shell-db
```

### Tests

```bash
make test
make test-cov
```

### Common agent tasks

| Task | What to ask Cursor |
|------|-------------------|
| Add documentation | Triggers `docs-router` — agent asks inline vs separate file |
| Audit frontend code | "Run fallow health on the frontend" |
| Build UI components | "Design a dashboard card" (uses `frontend-design`) |
| Create a PR | Uses GitHub MCP if `GITHUB_TOKEN` is set |

---

## Cursor vs Claude Code

Both tools read from the same `.agents/skills/` directory:

| | Cursor | Claude Code |
|---|--------|-------------|
| Config | `.cursor/settings.json` | `.claude/settings.json` |
| Registration | `customRules` array | `customSkills` array + `triggers` |
| Skill path | `../.agents/skills/<name>/SKILL.md` | `../.agents/skills/<name>/SKILL.md` |
| Personal overrides | — | `.claude/settings.local.json` (gitignored) |

---

## Related docs

- [`README.md`](./README.md) — project overview and skills summary
- [`SETUP.md`](./SETUP.md) — full environment setup
- [`QUICK_REFERENCE.md`](./QUICK_REFERENCE.md) — command cheat sheet
- [`.agents/skills/docs-router/SKILL.md`](./.agents/skills/docs-router/SKILL.md) — documentation routing skill
