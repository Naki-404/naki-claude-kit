---
name: naki-docker-deploy
description: Containerizing and shipping services, covering Dockerfiles, Docker Compose, configuration and secrets, health checks, CI/CD pipelines, releases and rollback. Use when writing or reviewing a Dockerfile or compose file, setting up a pipeline, preparing a deployment, or planning how to roll back a bad release.
---

# Docker and Deployment

## When to use

- Writing or reviewing a `Dockerfile`, `compose.yaml`, `.dockerignore`.
- Setting up CI that builds, tests, scans and pushes images.
- Preparing a release or deciding on a rollback plan.
- Debugging a container that works locally but not in the target environment.

Deploys touch shared systems: apply `naki-safety` and ask the user before pushing images, deploying, or changing production configuration. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Dockerfile rules

1. **Pin the base image** to a specific version (`python:3.12.7-slim-bookworm`), ideally with digest for production.
2. **Multi-stage builds:** compile and install in a builder stage, copy only runtime artifacts into a slim final stage.
3. **Order layers for cache:** copy dependency manifests and install first, then copy source.
4. **Run as a non-root user** with a fixed UID.
5. **No secrets in the image:** not in `ENV`, `ARG`, copied files or layer history. Use BuildKit secret mounts for build-time credentials.
6. **`.dockerignore`** excludes `.git`, `.venv`, `node_modules`, `__pycache__`, `.env`, test data, local datasets.
7. **One process per container,** exec form `CMD ["..."]` so signals reach the process; handle SIGTERM for graceful shutdown.
8. **Add a `HEALTHCHECK`** or rely on the orchestrator's probes, hitting a cheap endpoint.
9. **Images are immutable and environment-agnostic:** same image for staging and prod, config from environment.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12.7-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv export --frozen --no-dev -o requirements.txt \
    && pip wheel --wheel-dir /wheels -r requirements.txt
COPY src ./src
RUN pip wheel --no-deps --wheel-dir /wheels .

FROM python:3.12.7-slim-bookworm
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Compose for local and small deployments

```yaml
services:
  api:
    build: .
    env_file: .env
    ports: ["127.0.0.1:8000:8000"]
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
  db:
    image: postgres:16.4
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets: [db_password]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 10
secrets:
  db_password:
    file: ./secrets/db_password.txt
volumes:
  pgdata:
```

- Bind published ports to `127.0.0.1` unless the service must be reachable from other hosts.
- `depends_on` with `service_healthy` only orders startup; the app must still retry its DB connection.
- Named volumes for data; never store state in the container filesystem.
- On Windows, watch line endings in shell scripts copied into images (`.gitattributes`: `*.sh text eol=lf`).

## Configuration and secrets

- Twelve-factor style: config via environment variables, validated at startup (fail fast on missing values).
- Commit `.env.example` with placeholder values; keep `.env` in `.gitignore`.
- Production secrets come from a secret store (cloud key vault, orchestrator secrets) mounted as files or injected env, rotated without rebuilding images.
- Never print config with secrets at startup; log which keys are set, not their values.

## Health checks

| Probe | Question | Should check |
|---|---|---|
| liveness `/healthz` | is the process stuck? | process responds; no dependency calls |
| readiness `/readyz` | can it take traffic? | DB reachable, migrations applied, warm caches |
| startup | has it finished booting? | for slow starts, so liveness does not kill it early |

A liveness probe that checks the database restarts every replica when the database blips. Keep it local.

## CI/CD pipeline

1. **Lint and test** on every push and PR (ruff, type check, pytest, frontend tests).
2. **Build** the image once, tagged with the commit SHA (`app:3f9c2a1`), not only `latest`.
3. **Scan** image and dependencies (for example Trivy, pip-audit, npm audit); fail on critical findings with a fix available.
4. **Push** to the registry only from the main branch or tags.
5. **Deploy to staging** automatically; run smoke tests.
6. **Promote the same image** to production with a manual approval or tag.
7. **Run migrations** as a separate, explicit step before the new code serves traffic, and only backward-compatible ones (see `naki-postgres`).

CI secrets live in the CI secret store, scoped to the jobs that need them; forks and PR builds get no deploy credentials.

## Release and rollback

- Keep the previous image tag deployable; rollback is redeploying the prior SHA, not rebuilding.
- Database migrations must be compatible with both the old and new code during the rollout (expand and contract), or rollback breaks.
- Use rolling or blue-green deploys with readiness gates; watch error rate and latency for the first minutes.
- Feature flags decouple deploying from releasing risky behavior.
- Write down the rollback command before deploying.

## Workflow

1. Write or update `Dockerfile` and `.dockerignore`; build locally: `docker build -t app:dev .`
2. Run with Compose; check health endpoints and logs (`docker compose logs -f api`).
3. Check image size and user: `docker image ls app:dev`, `docker run --rm app:dev id`.
4. Scan the image; fix critical issues.
5. Update CI; confirm the pipeline runs green on a branch.
6. Ask the user before pushing images or deploying anywhere shared.

## Checklist

- [ ] Base image pinned; multi-stage; non-root user.
- [ ] No secrets in image layers, build args or repo.
- [ ] `.dockerignore` present and excludes data, venvs, `.git`, `.env`.
- [ ] Liveness and readiness separated.
- [ ] Graceful shutdown on SIGTERM.
- [ ] Images tagged by commit SHA; same image promoted across environments.
- [ ] Migrations backward compatible; rollback command known.

## Common mistakes

- `COPY . .` before installing dependencies, busting the cache on every change.
- Using `latest` tags so nobody knows what is running.
- Shell form `CMD uvicorn ...` so SIGTERM never reaches the app and shutdown takes the full kill timeout.
- Publishing the database port to `0.0.0.0` on a cloud VM.
- Baking `.env` into the image through `COPY . .`.
- Rolling back code after a migration dropped a column the old code needs.
