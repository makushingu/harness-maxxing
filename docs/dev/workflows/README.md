# GitHub Actions workflows (to install)

`ci.yml` (server pytest with uv, web typecheck + build, pc-agent `go test`) and `cla.yml` (CLA Assistant Lite,
signatures on the branch `cla-signatures`, document `CLA.md`) belong in `.github/workflows/`. They are kept here
because pushing a workflow file needs a GitHub token with the `workflow` scope. A maintainer with that scope
installs them once:

```bash
git mv docs/dev/workflows/ci.yml docs/dev/workflows/cla.yml .github/workflows/ && git rm -q docs/dev/workflows/README.md
```
