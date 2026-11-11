---
name: naki-sec-cloud-containers
description: Cloud and container security: IAM least privilege, storage exposure, network boundaries, secrets, image hardening, Kubernetes basics and cloud audit logs. Use when reviewing cloud IAM or infrastructure code, hardening Dockerfiles or Kubernetes manifests, or investigating alerts from cloud audit or container runtime logs.
---

# Cloud and Container Security

## When to use

- Reviewing IAM policies, Terraform/Bicep/CloudFormation, Dockerfiles, Compose files or Kubernetes manifests.
- Setting up a new cloud account, subscription or project with secure defaults.
- Investigating alerts from cloud audit logs (AWS CloudTrail, Azure Activity Log and Entra ID sign-in logs, GCP Cloud Audit Logs) or container runtime.
- Building detections for cloud and container attack techniques.

Deployment mechanics are in `naki-docker-deploy`. Image and dependency scanning in CI is in `naki-sec-devsecops`. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Core rules

1. Least privilege: grant specific actions on specific resources; no wildcard admin for workloads.
2. No long-lived keys where a managed identity, workload identity or role can be used.
3. Storage is private by default; public access needs an explicit, reviewed exception.
4. Audit logging is enabled everywhere, sent to a separate account or workspace the workload cannot modify.
5. Containers run as non-root, with a read-only root file system where possible, minimal base images, and no secrets baked in.
6. Infrastructure is code, reviewed like code. Manual console changes are drift to detect.
7. Protect the root or global admin accounts: MFA, no daily use, alert on any use.

## IAM review

| Smell | Why it matters | Better |
|---|---|---|
| `Action: "*"` or Owner/Contributor on subscription for an app | Full takeover if the app is compromised | List required actions, scope to resource |
| Wildcard resource on data actions | Reads every bucket or vault | Specific ARNs / resource ids |
| Long-lived access keys for CI | Keys leak in logs and forks | OIDC federation from CI to cloud role |
| Users with both admin and daily use | Phishing one user is admin compromise | Separate admin identity, just-in-time elevation |
| Permission to change IAM (`iam:PassRole`, role assignment write) | Privilege escalation path | Restrict and alert on use |
| Unused roles and keys | Forgotten attack surface | Remove after 90 days unused |

## Storage and network exposure

- Block public access at the account or subscription level for object storage; review exceptions.
- Encrypt at rest (default) and in transit; customer-managed keys for regulated data.
- Databases and caches have no public endpoints; use private networking.
- Management ports (SSH 22, RDP 3389, Kubernetes API, database ports) are never open to `0.0.0.0/0`.
- Metadata service: require token-based access (for example IMDSv2) so SSRF cannot read credentials easily.

## Container image hardening

```dockerfile
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home app
COPY --from=build /install /usr/local
COPY --chown=app:app src/ /app/src/
USER 10001
WORKDIR /app
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["python", "-m", "src.main"]
```

Checklist for images: pinned base image (digest for production), multi-stage build, non-root `USER`, no secrets in layers or build args, `.dockerignore` excludes `.env` and `.git`, scanned for CVEs, rebuilt regularly.

Runtime: drop all Linux capabilities and add back only what is needed, `no-new-privileges`, no `--privileged`, never mount the Docker socket into an application container, limit CPU and memory.

## Kubernetes basics

| Area | Secure setting |
|---|---|
| Pod security | `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: ["ALL"]`, Pod Security Standard `restricted` |
| RBAC | Namespace-scoped Roles, no `cluster-admin` for workloads, no wildcard verbs on secrets |
| Service accounts | One per workload, `automountServiceAccountToken: false` unless needed |
| Network | Default-deny NetworkPolicy per namespace, then allow specific flows |
| Secrets | External secret store or encrypted etcd; never in ConfigMaps or images |
| Images | Admission policy allowing only trusted registries and signed images |
| API server | Not public, or restricted by IP and strong auth; audit logging on |

## Detection: cloud audit events worth alerting on

| Activity | Example events (generic) | ATT&CK |
|---|---|---|
| Audit logging disabled or changed | Stop or delete trail, change diagnostic settings | T1562.008 |
| New access key or credential for a user | Create access key, add service principal secret | T1098.001 |
| Privilege grant | Attach admin policy, new role assignment at subscription scope | T1098.003 |
| Root or global admin sign-in | Any root console login | T1078.004 |
| Storage made public | Bucket policy or ACL allows all users, public blob access enabled | T1530 follow-up risk |
| Mass reads of storage or secrets | Spike of get-object or get-secret by one identity | T1530, T1552 |
| Unusual region or service use | Compute launched in unused regions, GPU instances | T1496 Resource Hijacking |
| Instance metadata credentials used outside instance | Role session used from IP not belonging to the workload | T1552.005 |
| Defense changes | Security group opened to `0.0.0.0/0` on admin ports | T1562.007 |

Container runtime signals: shell spawned in a container that normally never runs one (T1059.004), outbound connections to mining pools (T1496), writes to binary directories, `kubectl exec` into production pods (T1609), new privileged pods or hostPath mounts (T1610, T1611).

## Investigating a cloud alert

1. Identify the principal: user, role, service principal or key id, and who owns it.
2. Pull every action by that principal over the last 30 days; compare to its baseline.
3. Check source IPs and user agents (CLI, SDK, console, unusual tools).
4. List what changed: new identities, keys, policies, resources, network rules.
5. Check data access: storage reads, secret reads, database snapshots, exports.
6. Contain: disable or revoke the key or session, remove added permissions, block IPs (see `naki-sec-incident-response`).
7. Hunt for persistence: other keys, new users, trust policy changes, federated identities, scheduled functions.

## Review workflow for IaC

1. Grep for wildcards and public settings: `"*"`, `0.0.0.0/0`, `public`, `privileged`, `hostPath`, `AllowAll`.
2. Run a policy scanner on the IaC (for example Checkov, tfsec, Trivy config) and review each finding.
3. Confirm logging resources exist and are protected.
4. Check secrets are references to a vault, not literals.
5. Report with severity, resource, evidence and the exact fix.

## Common mistakes

- Leaving the CI pipeline with an admin role "temporarily".
- Sending audit logs to the same account an attacker can control, where they can delete them.
- Assuming private networking covers storage while a public access policy is still set on one bucket.
- Running containers as root because the base image does, and mounting host paths for convenience.
- Treating unusual compute spend only as a billing problem; it is often the first sign of a stolen key.
