# Soothe Builtin Skills

This directory contains builtin skills that ship with Soothe. Skills are self-contained packages that extend the agent's capabilities with specialized knowledge, workflows, and tools.

## Available Skills

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| **weather** | Get current weather and forecasts (no API key required) | curl |
| **github** | Interact with GitHub via `gh` CLI | gh |
| **clawhub** | Search and install skills from ClawHub registry | Node.js/npx |
| **skill-creator** | Create and package new AgentSkills (deferred) | None |
| **mcp-builder** | Build MCP servers in Python or Node/TypeScript (deferred) | None |

## Skill Format

Each skill follows the AgentSkills specification:

```
skill-name/
├── SKILL.md          # Required: YAML frontmatter + instructions
├── scripts/          # Optional: Executable helper scripts
├── references/       # Optional: Documentation loaded as needed
└── assets/           # Optional: Templates, resources
```

## Discovery

Builtin skills are automatically discovered via ``iter_skill_roots()`` /
``get_built_in_skills_paths()``. Host packages (e.g. fj) can register extra
roots:

```python
from pathlib import Path
from soothe_nano.skills import register_builtin_skill_root

register_builtin_skill_root(Path(__file__).parent / "builtin_skills")
```

Or via config:

```yaml
builtin_skill_roots:
  - /path/to/package/builtin_skills
```

User skills can also be added via ``SootheConfig.skills`` / ``skills:`` in YAML:

```python
from soothe_nano.config import SootheConfig

config = SootheConfig(
    skills=["~/.soothe/skills/my-reviewer", "/path/to/custom/skills/deploy"]
)
```

## Creating New Skills

See the `skill-creator` skill for comprehensive guidance on creating new skills.

Quick start (project workspace — preferred):
```bash
WORKSPACE="$(pwd)"   # Soothe workspace root
SKILLS_DIR="${WORKSPACE}/.soothe/skills"
mkdir -p "${SKILLS_DIR}"

# Initialize a new skill
python packages/soothe/src/soothe/built_in_skills/skill-creator/scripts/init_skill.py \
  my-skill --path "${SKILLS_DIR}"

# Edit the SKILL.md
cd "${SKILLS_DIR}/my-skill"
# Edit SKILL.md...

# Package the skill
python packages/soothe/src/soothe/built_in_skills/skill-creator/scripts/package_skill.py \
  "${SKILLS_DIR}/my-skill"
```

User-wide install: use `--path ~/.soothe/skills` instead of `${SKILLS_DIR}`.

## Progressive Disclosure

Skills use a three-level loading system:
1. **Metadata** (name + description) - Always loaded (~100 words)
2. **SKILL.md body** - Loaded when skill triggers (<5k words)
3. **Bundled resources** - Loaded as needed

This keeps context lean while providing unlimited depth when needed.

## External Dependencies

Some skills require external CLI tools:

| Skill | Tool | Install |
|-------|------|---------|
| github | `gh` | `brew install gh` or `apt install gh` |

These are documented in each skill's metadata for graceful degradation.