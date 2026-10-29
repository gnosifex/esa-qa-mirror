# CLAUDE.md

## Commits and pull requests

- Commit author: `Claude <noreply@anthropic.com>`. Merges run through the
  `gnosifex` GitHub account and its noreply address — both are fine.
- Do **not** add Claude Code session links (`Claude-Session: https://claude.ai/code/…`
  or similar) to commit messages or pull request descriptions.

## Checks before pushing

```
pip install -r requirements.txt pytest ruff
ruff check .
pytest -q
```
