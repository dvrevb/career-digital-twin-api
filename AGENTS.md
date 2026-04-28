## Commit discipline

- Small, atomic commits: one logical change each. If the subject line needs "and", split the commit.
- Commit as soon as a slice works — don't batch unrelated changes.
- Messages: imperative mood ("add chat widget", not "added chat widget"). Subject line under 72 chars.
- If lint or typecheck fails, fix it in the same commit, not a follow-up "fix lint" commit.
- Feature branches only. Never commit straight to main unless explicitly asked.
- Never skip hooks (`--no-verify`). Never amend a commit without being told.
- Never add AI attribution (no `Co-Authored-By: Claude`, no "generated with" lines, nothing).
