---
name: naki-sec-devsecops
description: Secure software delivery: secrets scanning, dependency and supply-chain checks, SAST in CI, container image checks, pipeline hardening, SBOM and signed builds. Use when setting up or reviewing a CI pipeline, adding security gates, handling a leaked secret, or adding or pinning dependencies.
---

# DevSecOps

Put cheap, fast security checks where code changes happen, and make the pipeline itself hard to abuse. A gate that
blocks every build gets disabled; tune gates so they block only what must be fixed now.

## When to use

- Creating or changing a CI workflow (GitHub Actions, GitLab CI, Azure Pipelines).
- Adding a dependency, base image or third-party action.
- A secret was committed or printed in a log.
- Preparing a release that needs an SBOM or signed artifacts.

## Core rules

1. Secrets never live in the repo, images or logs. Use the CI secret store or a vault; inject at runtime.
2. A leaked secret is rotated first, then removed from history. Removing it from git does not un-leak it.
3. Pin dependencies with a lock file and hashes where the tooling supports it. Pin CI actions to a commit SHA.
4. CI jobs get least privilege: read-only tokens by default, write only in the job that needs it.
5. Untrusted code (forks, external PRs) never runs with access to secrets.
6. Security gates fail the build only on high-confidence, high-severity findings; everything else is reported.
7. Build once, promote the same artifact through environments; sign it and record its SBOM.
8. Pre-commit hooks help developers but are not a control. CI repeats every check.

## Pipeline stages and checks

| Stage | Check | Example tools | Gate |
|---|---|---|---|
| Pre-commit | Secrets, lint, format | gitleaks, detect-secrets, ruff | Warn locally |
| PR | Secrets scan on diff | gitleaks | Block on any verified secret |
| PR | SAST | Semgrep, Bandit, CodeQL | Block on high severity, new findings only |
| PR | Dependency audit | pip-audit, npm audit, OSV-Scanner | Block on KEV or critical with fix available |
| PR | IaC and config | Checkov, tfsec, hadolint | Block on public storage, open admin ports |
| Build | Image scan | Trivy, Grype | Block on critical with fix |
| Build | SBOM | Syft, CycloneDX tools | Always produce, store with artifact |
| Release | Sign artifact | cosign, Sigstore | Required for deploy |
| Deploy | Verify signature, policy | admission policy | Reject unsigned |

"New findings only" means compare with the base branch so legacy debt does not block every PR; track the legacy
backlog separately (see `naki-sec-vuln-management`).

## Secrets handling

Where secrets go:

- Local development: `.env` file listed in `.gitignore`, plus a committed `.env.example` with placeholders.
- CI: the platform secret store, scoped to environment (staging and production separate).
- Runtime: environment variables or a secret manager; mounted files with restricted permissions.

Leaked secret runbook:

1. Revoke or rotate the credential immediately at the provider.
2. Check provider logs for use of the credential since the leak time.
3. Remove it from the code and, if the repo is shared, rewrite history (`git filter-repo`) in coordination with the team.
4. Add a scanner rule or allowlist fix so the same pattern is caught next time.
5. Record the incident (see `naki-sec-incident-response`).

```bash
# Scan working tree and full history
gitleaks detect --source . --redact
# Scan only staged changes before commit
gitleaks protect --staged --redact
```

## Hardening a CI workflow (GitHub Actions example)

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read            # default for all jobs
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>  # v4, pin the SHA
        with:
          persist-credentials: false
      - uses: actions/setup-python@<full-commit-sha>  # v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt --require-hashes
      - run: pip-audit -r requirements.txt
      - run: pytest -q
```

Checklist for workflows:

- [ ] Top-level `permissions` set to read-only; jobs widen only as needed.
- [ ] Third-party actions pinned to full commit SHA; updates via a bot with review.
- [ ] No `pull_request_target` with checkout of PR code.
- [ ] User-controlled strings (PR titles, branch names) never interpolated directly into `run:` scripts; pass via env.
- [ ] Secrets only in jobs and environments that need them; production deploy requires approval.
- [ ] Self-hosted runners not used for public repositories.
- [ ] Artifacts and caches do not contain secrets.

## Supply chain

- Before adding a dependency: check maintenance activity, download count, known advisories, license, and whether a
  smaller standard-library solution exists (see `naki-search-first`).
- Watch for typosquats and dependency confusion: names close to popular packages, internal names that also exist on
  the public index. Configure the package manager to use the internal index for internal names.
- Install with lock files in CI (`npm ci`, `pip install --require-hashes`, `uv sync --frozen`).
- Base images: use minimal official images, pin by digest, rebuild regularly to pick up patches.
- Generate an SBOM per release and keep it; it answers "are we affected?" when the next advisory lands.

## SAST tuning

1. Start with a small, high-precision rule set for your languages.
2. Run on the diff in PRs; run full scans nightly.
3. Triage each new rule's findings once; mark false positives with an inline reason, not a global disable.
4. Promote a rule to blocking only after its false positive rate is low on your code.

## Common mistakes

- Deleting a committed key from the latest commit and calling it fixed without rotating.
- Workflows with `permissions: write-all` because one job needed to post a comment.
- Pinning actions by tag (`@v4`), which can be moved.
- Blocking PRs on hundreds of legacy findings, which teaches people to bypass the gate.
- Printing environment variables in debug steps.
- Building different artifacts per environment, so what was tested is not what was deployed.

## Report template

```markdown
## Pipeline security review: <repo>
- Secrets: scanner in PR? history scanned? findings:
- Dependencies: lock file, hashes, audit gate:
- SAST: tool, rule set, blocking policy:
- Images: base, digest pin, scan gate:
- Workflow permissions and action pinning:
- Release: SBOM, signing, promotion:
- Top fixes (ordered):
```

Follow the project rules skill if the project has one (for example `naki-myapp`).
