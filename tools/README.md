# Skill Validation Tools

## validate-skill.py

Validate SKILL.md metadata before submitting a PR.

### Usage

```bash
# Validate a single skill
python tools/validate-skill.py skills/my-new-skill/

# Validate all skills
python tools/validate-skill.py --all
```

### What it checks

- SKILL.md exists in the skill directory
- Valid YAML frontmatter (between `---` markers)
- Required fields present: `name`, `description`, `domain`, `subdomain`, `tags`
- Name is kebab-case, 1–64 characters
- Description is at least 50 characters (no upper limit; multi-line folded scalars are valid)
- Domain is `cybersecurity`
- Subdomain is from the allowed list
- Tags is a list with at least 2 items

### Requirements

Python 3.8+ (stdlib only, no external dependencies)

## Data egress audit

Use `audit-data-egress.py` to inventory scripts that may send processed artifacts, indicators, logs, or credentials to third-party services. The scanner reports hardcoded URLs, outbound network imports/calls, and disabled TLS verification so teams can review and allowlist approved integrations before running skills with company data.

```bash
python3 tools/audit-data-egress.py --format markdown > data-egress-report.md
python3 tools/audit-data-egress.py --fail-on high
```

See [`../DATA_EGRESS.md`](../DATA_EGRESS.md) for the recommended review workflow and runtime controls.

