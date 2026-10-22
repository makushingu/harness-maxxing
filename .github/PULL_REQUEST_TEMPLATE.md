## What and why

<!-- What this pull request changes and why. Link the issue: "Closes #123". Features need an agreed issue first. -->

## How it was tested

<!-- Commands you ran, what you checked by hand (screenshots for UI changes). -->

## Checklist

- [ ] An issue was agreed with a maintainer first (features and bigger changes)
- [ ] Server tests pass: `cd server && uv sync && uv run pytest`
- [ ] Tests added or updated for this change (a bug fix comes with a test that fails without it)
- [ ] Web changes only: `cd web && npm ci && npm run typecheck && npm run build`, and the rebuilt `web/dist` is committed
- [ ] No web change: `web/dist` is not in the diff
- [ ] `pc-agent/` touched: `cd pc-agent && go test ./...` passes
- [ ] `CHANGELOG.md` (public, plain language) and `docs/dev/CHANGES.md` (maintainers) updated
- [ ] User docs (`docs/user/`) updated for every visible change; UI texts in English and French
- [ ] No personal data, secrets, real domains or server paths
- [ ] I have signed the [CLA](../CLA.md) (comment `I have read the CLA Document and I hereby sign the CLA`)
