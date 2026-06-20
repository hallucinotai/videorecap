# docs-router Skill

Ensures every piece of documentation is correctly routed — either written directly into `README.md`
or placed in a dedicated file that is linked from `README.md` — so that `README.md` always serves
as the single root entry point for any project.

## When to Use

Trigger this skill whenever asked to:
- Create, write, generate, or add documentation
- Write READMEs, guides, API references, setup instructions, changelogs, architecture docs, tutorials, how-tos, contributing guides
- Produce any Markdown content intended for the project repository

**Phrases that trigger this skill:**
- "create documentation"
- "write docs"
- "add a README section"
- "document this"
- "generate a guide"
- "write a CHANGELOG"
- "add API docs"

---

## Documentation Philosophy

This project follows a **simple, flat documentation hierarchy** to keep navigation intuitive and discovery easy:

### Core Principles

1. **README.md as Single Root** — All documentation either lives in `README.md` (inline) or is one link away from it (separate file linked from README.md). No multi-level chains or deep hierarchies.

2. **Suggest First, Don't Auto-Create** — Before creating any new documentation file, suggest it to the user with clear reasoning:
   - **Why it helps users:** Explain how this doc improves navigation, clarity, or discoverability
   - **Navigation ease:** Only suggest if users can easily find it from README.md (one click)
   - **Simplicity:** If explanation feels complex, reconsider — keep it simple

3. **User Approval Required** — Wait for explicit user approval before creating a new `.md` file. Suggest but don't auto-create. Explain the benefit and how simple it is to use.

4. **Link Only to Existing Docs** — When creating new documentation, only link to existing `.md` files. Do not propose creating chains of new files (A → B → C). Keep it flat: README.md → destination file.

5. **One Level, Rare Exceptions** — The ideal is README.md linking directly to content files. Only in rare cases where a referenced document already exists and needs cross-reference is linking between documentation files acceptable.

**Example ✅ Good:**
```
README.md
  → api-reference.md
  → setup.md
  → troubleshooting.md
```

**Example ❌ Avoid:**
```
README.md
  → guides/
      → api/api-reference.md
      → setup/installation.md
      → setup/troubleshooting.md
```

---

## Step 0 — Ask Before Writing

**Before producing any documentation content**, ask exactly one question:

> Should this documentation go **directly in `README.md`**, or in a **separate file linked from `README.md`**?
> - **Directly in README.md** — content is added inline to the README
> - **Separate file linked from README.md** — a new `.md` file is created and a link is added under a matching topic heading in README.md

**Wait for the user's answer. Do not guess or proceed without it.**

---

## Step 1A — If Answer is "Directly in README.md"

1. Open (or create) `README.md` in the project root
2. Write the documentation content inline, under an appropriate heading
3. Place the new section logically (e.g., after existing related sections, before unrelated ones)
4. Do **not** create any additional files

**Example result:**
```
README.md
  ## Installation
  ...content added here...
```

---

## Step 1B — If Answer is "Separate File Linked from README.md"

### 1. Determine the Filename
- Derive from the topic of the documentation
- Use lowercase, hyphen-separated words: e.g., `api-reference.md`, `contributing.md`, `architecture.md`
- If user specifies a filename, use that exactly
- Place in project root unless user specifies a subdirectory (e.g., `docs/`)

### 2. Create the Separate File
- Write all documentation content into the new `.md` file
- Start with a top-level heading (`#`) matching the topic name

### 3. Update README.md — Link Under Matching Topic Heading
- Open (or create) `README.md`
- Find or create a section heading in README.md matching the topic (filename without `.md`, title-cased)
  - If matching heading exists → add link under it
  - If no matching heading exists → append new heading at bottom of README.md
- Add Markdown link in this format:

```markdown
## <Topic Name>

See [<Topic Name>](./<filename>.md)
```

- If section already has content or other links, append new link below existing ones

**Example result:**
```
README.md
  ## Api Reference
  See [Api Reference](./api-reference.md)

api-reference.md
  # Api Reference
  ...content...
```

---

## Naming Conventions

| Topic Asked For | Filename | README Heading |
|---|---|---|
| API Reference / API docs | `api-reference.md` | `## Api Reference` |
| Setup / Installation | `setup.md` | `## Setup` |
| Contributing guide | `contributing.md` | `## Contributing` |
| Architecture overview | `architecture.md` | `## Architecture` |
| Changelog | `changelog.md` | `## Changelog` |
| Deployment guide | `deployment.md` | `## Deployment` |
| Troubleshooting | `troubleshooting.md` | `## Troubleshooting` |
| User guide / Usage | `usage.md` | `## Usage` |
| Admin guide | `admin-guide.md` | `## Admin Guide` |
| Database schema | `database-schema.md` | `## Database Schema` |

For anything not listed, derive the name from the topic: lowercase, hyphen-separated.

---

## README.md Creation (If It Doesn't Exist)

If `README.md` does not exist:
1. Create with minimal structure:
   ```markdown
   # <Project Name>

   > Brief description of the project.

   ```
2. Then proceed with Step 1A or 1B as determined by user's answer

---

## Rules

- **Always ask first** — Never skip the routing question
- **README.md is the root** — Every piece of documentation must either live in it or be reachable from it
- **One link per topic heading** — Don't duplicate links for the same file
- **Never create orphaned docs** — A separate file with no README.md link violates this contract
- **Preserve existing structure** — Add new documentation logically within existing README organization
- **Use consistent formatting** — Follow existing README style and tone

---

## Example Workflows

### Workflow 1: Add to README.md Directly
```
User: "Create an admin guide"
↓
Skill asks: "Directly in README.md or separate file?"
↓
User: "Directly in README.md"
↓
Add new "## Admin Guide" section to README.md with full content inline
```

### Workflow 2: Create Separate File
```
User: "Document the database schema"
↓
Skill asks: "Directly in README.md or separate file?"
↓
User: "Separate file"
↓
Create: database-schema.md with full content
Update: README.md with "## Database Schema" section and link to database-schema.md
```

### Workflow 3: Link to Existing Section
```
User: "Add API documentation"
↓
Skill asks: "Directly in README.md or separate file?"
↓
User: "Separate file"
↓
Create: api-reference.md
Update: README.md - if "## Api Reference" exists, add link; if not, create heading and add link
```
