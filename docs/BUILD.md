# Build & release process

A starting point for anyone diving into how `labeljetty` is versioned, built, and
shipped. The user-facing summary lives in the [README](../README.md#releases--versioning);
this document is the deeper reference.

## Overview

There are three build outputs, all driven from a single source of truth — the **git tag**:

| Output         | Built by                          | Trigger              |
| -------------- | --------------------------------- | -------------------- |
| PyPI package   | `hatchling` + `hatch-vcs`         | GitHub Release       |
| Docker image   | `Dockerfile` (multi-arch)         | GitHub Release       |
| Local dev image | `build-container.sh`             | manual               |

## Versioning (`hatch-vcs`)

The version is **not** stored in `pyproject.toml`. Instead:

- `pyproject.toml` declares `dynamic = ["version"]` and configures
  `[tool.hatch.version] source = "vcs"`.
- [`hatch-vcs`](https://github.com/ofek/hatch-vcs) (a thin wrapper over
  `setuptools_scm`) derives the version from the latest reachable git tag.
- Tags are plain `0.0.1` (an optional leading `v` is also accepted).

How the version flows at build time:

- **On an exact tag** (`0.1.0`) → version is exactly `0.1.0`. This is the case in CI,
  because the release workflow checks out the tag.
- **Ahead of a tag / no tag** → `setuptools_scm` produces a dev version like
  `0.1.dev8+g6c5de49` (or `0.0.0`-ish with no tags at all). Fine for local work,
  never published.

A build hook writes the resolved version into `src/labeljetty/_version.py`
(`[tool.hatch.build.hooks.vcs]`). That file is **generated and gitignored** —
regenerated on every build, never edited or committed.

### Runtime resolution

[`src/labeljetty/version.py`](../src/labeljetty/version.py) `get_version()` resolves the
running version in priority order:

1. **`LABELJETTY_VERSION` env var** — how the Docker image is branded (see below).
2. **Installed package metadata** — `importlib.metadata.version("labeljetty")`, set from
   the wheel that `hatch-vcs` stamped at build time.
3. **`_version.py`** — the generated file, present in an editable/dev install.
4. **`0.0.0+unknown`** — running from a raw source tree with no metadata.

This single function backs `__version__`, the FastAPI `app.version`, the
`GET /api/version` endpoint, and the web-UI footer.

### Why the lockfile stays stable

A dynamic version would normally fight a frozen lockfile. `uv lock` records the project's
own version as `(dynamic)` rather than pinning a number, so `uv sync --frozen` in the
Dockerfile never fails on a version mismatch. If you change versioning config, re-run
`uv lock`.

## Docker image

See [`Dockerfile`](../Dockerfile). Key points:

- Base `python:3.11-slim`; runtime system deps are **`libusb-1.0-0`** (pyusb talks to the
  printer over it) and **`fonts-dejavu-core`** (text/markdown rendering uses DejaVu Sans).
- Dependencies are installed with `uv sync --frozen --no-dev --no-editable` from the
  committed `uv.lock` — reproducible, no dev/test tooling in the image.
- **Version branding without `.git`:** the image is built with `--build-arg VERSION=<tag>`.
  The Dockerfile maps that to two env vars:
  - `SETUPTOOLS_SCM_PRETEND_VERSION` — lets `hatch-vcs` resolve the version during
    `uv sync` even though the `.git` directory is excluded from the build context (see
    [`.dockerignore`](../.dockerignore)).
  - `LABELJETTY_VERSION` — read at runtime by `get_version()` (priority 1 above), so the
    container reports its release.
- Container-friendly defaults: binds `0.0.0.0:8888`, stores the SQLite DB and images under
  the `/data` volume (`SQLITE_PATH`, `IMAGE_STORAGE_DIRECTORY`). `PRINTER_USB` has no
  default and must be supplied at run time.

### Multi-arch

Built for `linux/amd64` and `linux/arm64` and pushed as one manifest list, so clients pull
the matching arch automatically. `arm64` covers 64-bit Raspberry Pi OS on Pi 3/4/5. 32-bit
(`arm/v7` / `arm/v6`: 32-bit Pi OS, Pi Zero/Zero 2 W, Pi 1/2) is intentionally **not** built
— it roughly doubles emulated CI build time and depends on `arm/v7` wheels existing for
`pypdfium2`/`pillow`. Revisit if an issue asks for it: add the platform to the `platforms:`
list in [`docker.yml`](../.github/workflows/docker.yml) and verify the dependency wheels
resolve under QEMU.

### Local builds

[`build-container.sh`](../build-container.sh) is for quick hands-on testing. It derives the
`VERSION` build-arg from git: an exact version tag if HEAD is on one, otherwise a PEP440-valid
local marker (`0.0.0+local.<hash>`) — raw `git describe` output (`<hash>-dirty`) is *not* a
valid version and would break the build. Override the image name/tag via `IMAGE=` / `TAG=`
env vars; extra args pass through to `docker build`.

## CI workflows

All under [`.github/workflows/`](../.github/workflows/). `pypi.yml` and `docker.yml` fire on
`release: published`; `docker-dev.yml` fires on push to `main`.

### `pypi.yml`

1. Checkout with `fetch-depth: 0` — `hatch-vcs` needs the tag history, a shallow clone hides
   it.
2. `uv build` → sdist + wheel (version from the tag).
3. `uv publish --token $PYPI_API_TOKEN`.

### `docker.yml`

1. Compute tags from the release: always `:<version>`; `:beta` for a pre-release, `:latest`
   for a normal release.
2. `docker/setup-qemu-action` + `setup-buildx-action` for multi-arch.
3. Log in to Docker Hub, then `build-push-action` with `build-args: VERSION=<version>` and
   the computed tags. Layer cache via GitHub Actions cache (`type=gha`).

### `docker-dev.yml`

Bleeding-edge `:dev` channel, on every push to `main`. **`linux/amd64` only** — no QEMU, so
it's fast (the multi-arch images come from releases via `docker.yml`). The version is branded
as `0.0.0+dev.<short-sha>`. Not for production.

### Required secrets

| Secret               | Workflow                      | What it is                                            |
| -------------------- | ----------------------------- | ----------------------------------------------------- |
| `DOCKERHUB_USERNAME` | `docker.yml`, `docker-dev.yml` | Docker Hub login (needs push access to `motey/labeljetty`) |
| `DOCKERHUB_TOKEN`    | `docker.yml`, `docker-dev.yml` | Docker Hub access token (Account Settings → Security) |
| `PYPI_API_TOKEN`     | `pypi.yml`                    | PyPI API token (pypi.org → Account → API tokens)      |

## Cutting a release

1. Push your changes to `main`.
2. Create a **GitHub Release** with a tag in `0.0.1` form.
   - Normal release → Docker `latest` + `X.Y.Z`, and PyPI.
   - Pre-release → Docker `beta` + `X.Y.Z`, and PyPI.
3. Both workflows run automatically. Verify the image on Docker Hub and the package on PyPI.

## Where to look

| File                          | Responsibility                                  |
| ----------------------------- | ----------------------------------------------- |
| `pyproject.toml`              | Dynamic version config, build backend           |
| `src/labeljetty/version.py`   | Runtime version resolution                      |
| `Dockerfile` / `.dockerignore`| Image build, version branding                   |
| `build-container.sh`          | Local image build                               |
| `.github/workflows/pypi.yml`  | PyPI publish                                     |
| `.github/workflows/docker.yml`| Docker Hub publish (multi-arch, on release)      |
| `.github/workflows/docker-dev.yml` | Docker Hub `:dev` (amd64, on push to main)  |
