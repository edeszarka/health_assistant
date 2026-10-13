@AGENTS.md

# Claude Code specifics
- Base branch is `main`.
- Never read or print anything under data/, uploads/, zipped/, or any .env, *.pdf, *.zip file: they contain personal health data.
- Logic changes: use plan mode and get the plan approved before editing. Mechanical changes: a short plan is enough.
