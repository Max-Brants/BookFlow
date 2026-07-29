## Agent skills

### Issue tracker

Issues live as markdown files under `.scratch/<feature-slug>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

### Pull requests

When completed work is on a non-POC feature branch and is intended to merge into `main`, create a pull request with the `gh` CLI. Before creating it, inspect the branch status, recent commits, remote tracking, and the full diff from `main`; include any prerequisite commits in the review. Do not create a PR for throwaway prototype/POC branches unless explicitly requested.

### Local CI verification before pushing

Do not use GitHub Actions as the first complete validation pass. Before pushing a branch or a new PR revision, reproduce the CI jobs locally and only push after they pass. Run these commands from the repository root using Python 3.14, uv 0.11.3, and Node.js 24.

GitHub's Python job runs on Ubuntu. On Windows, run the final Python job from WSL2 or an equivalent local Linux environment using a clean LF checkout and uv-managed Python 3.14. Native Windows runs are useful for fast feedback but are not a CI substitute: POSIX permission tests, deletion semantics, and CRLF shell scripts can otherwise produce misleading failures.

Install or refresh dependencies when starting work and whenever a lockfile changes:

```bash
uv sync --locked --extra browser
cd src/frontend && npm ci && cd ../..
```

During implementation, run the smallest relevant checks for fast feedback. Before every push, run the complete Python job in the same order as `.github/workflows/ci.yml`:

```bash
uv run ruff check bookflow tests
uv run ruff format --check bookflow tests
uv run vulture bookflow
uv run basedpyright
uv run basedpyright tests --skipunannotated
uv run pytest tests/ -x --tb=short -m "not integration and not e2e"
```

If frontend files changed, also run the complete frontend job:

```bash
cd src/frontend
npm run lint
npm run format:check
npm run typecheck
npm run test:unit
npm run build
cd ../..
```

If Docker or packaging files changed, additionally run:

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg BUILDPLATFORM=linux/amd64 \
  --build-arg BUILDARCH=amd64 \
  --build-arg TARGETPLATFORM=linux/amd64 \
  --build-arg TARGETARCH=amd64 \
  --target bookflow \
  --build-arg BUILD_VERSION=local-ci \
  --build-arg RELEASE_VERSION=local-ci \
  --load .
```

The equivalent Make targets are `make python-lint python-format python-dead-code python-typecheck python-test` and `make frontend-lint frontend-format frontend-typecheck frontend-test build`. `make checks` alone is not a final CI pass because it omits unit tests and the production build.

Fix formatting locally with `make python-format-fix` and/or `make frontend-format-fix`, then rerun the affected complete job. The installed prek hooks provide early feedback, but do not replace the final pre-push commands. Leave GitHub Actions as the final clean-environment confirmation, not as the place to discover routine lint, formatting, type, test, or build failures.

### Local library development

Run the backend from the repository root (not Docker). Local library development uses builtin authentication and persistent local paths configured in the untracked `bookflow/.env`:

```bash
uv run --env-file bookflow/.env python -m bookflow
```

Run the frontend in a second terminal:

```bash
cd src/frontend && npm run dev
```

Vite serves on `http://localhost:5173` and proxies `/api` and `/socket.io` to the backend on `http://localhost:8084`.

Seed the local library database with Books 1-3 (available formats, no files, and in-flight) before exercising library UI. This resets the disposable local library DB and seed files, and creates local admin credentials `demo` / `demo`:

```bash
CONFIG_DIR="$PWD/.local/config" uv run python scripts/seed_library_demo.py
```

The script writes only under `.local/`; remove `.local/config/users.db` and `.local/seed-files/` to reset the seed data.
