## Codex prompt

Read `docs/design.md` for the full implementation spec.

One additional requirement not yet in the design doc:

### Required protected branches config

The tool must require a `.gh-clean.yml` config file in the repository root with a `protected_branches` list. The tool must refuse to run (report or delete) if this file is missing or the list is empty.

This is checked in addition to GitHub branch protection rules and rulesets — not instead of. The `--exclude` CLI flag adds to this list, not replaces it.

Sample `.gh-clean.yml`:

```yaml
protected_branches:
  - main
  - staging
  - production
```

If the config file is missing, exit with an error and print a sample config the user can copy.
