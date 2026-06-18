---
name: release
description: Prepare an inkscape-mcp release — bump the version in all three places, commit, tag, push, and (because it won't cascade automatically) manually trigger the PyPI publish workflow.
---

# Cutting an inkscape-mcp release

A release is: bump version → commit → tag `vX.Y.Z` → push main + tag → the **Release**
workflow auto-creates the GitHub release → **manually dispatch the Publish workflow** to
push to PyPI. Confirm the target version with the user before starting if it isn't given.

## 1. Prerequisites

```bash
git checkout main && git pull --ff-only
git status --short          # working tree should be clean (stash unrelated changes)
grep -n 'version = ' pyproject.toml      # current version, two lines
```

## 2. Bump the version

The version string lives in exactly three release-relevant locations. Set all three to the
new `X.Y.Z`:

- `pyproject.toml` — `[project]` `version` (~line 7)
- `pyproject.toml` — `[tool.fastmcp]` `version` (~line 118)
- `src/inkscape_mcp/__init__.py` — `__version__`

**Do not** touch `src/inkscape_mcp/transport.py` — its `version="1.0.0"` is a docstring
example, not the real version.

Edit the three lines directly with the **Edit tool** (one edit per occurrence). Do **not**
use `sed -i` here: under sandboxed Bash the in-place write is silently rolled back, so the
files look unchanged with no error — a faulty, easy-to-miss no-op. After editing, verify
with a sandbox-disabled grep (write tools are tracked by the harness, so they always stick):

```bash
grep -rn 'version = "<NEW>"\|__version__ = "<NEW>"' pyproject.toml src/inkscape_mcp/__init__.py
# expect 3 hits: pyproject.toml:7, pyproject.toml:118, __init__.py
```

## 3. Commit and tag

Keep the commit subject one line, no body unless something is non-obvious; no Co-Authored-By
trailer (repo convention).

```bash
git commit -am "Bump version to $NEW"
git tag "v$NEW"
git push origin main
git push origin "v$NEW"
```

## 4. Confirm the Release workflow

Pushing the `v*` tag triggers `.github/workflows/release.yml`, which builds the dist and
creates the GitHub release (notes auto-generated from commits since the last tag).

```bash
sleep 10
gh run list --workflow=release.yml --limit 1     # expect success
gh release view "v$NEW" --json name,isDraft,publishedAt
```

## 5. Manually publish to PyPI — REQUIRED

`.github/workflows/publish.yml` listens for `release: published`, **but GitHub does not
cascade workflow events from a release created by the built-in `GITHUB_TOKEN`** (which is
what the Release workflow uses). So the publish will NOT fire on its own — dispatch it by
hand every release:

```bash
gh workflow run publish.yml
sleep 10
gh run watch "$(gh run list --workflow=publish.yml --limit 1 --json databaseId -q '.[0].databaseId')" \
  --exit-status --interval 15
```

It re-runs tests, builds, and publishes via PyPI Trusted Publisher (OIDC — no token).

## 6. Verify

```bash
gh run list --limit 5     # CI, Security, Release, Publish should all be success
```

Tell the user the version is live, and link the release + PyPI page.

## Notes

- To skip the manual publish in future, either add `push: tags: ["v*"]` as a trigger to
  `publish.yml`, or have the Release workflow create the release with a PAT/GitHub App token
  so the `published` event cascades. Until then, step 5 is mandatory.
- If `git pull` is blocked by local changes, `git stash` → pull → `git stash pop`.
