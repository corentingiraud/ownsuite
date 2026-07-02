# Server sizing

How big a server to rent. OwnSuite runs on **one** machine, so the answer is a single VPS spec you can buy against. Pick a profile by which apps you enable, then read RAM / CPU / disk.

> **Short answer:** every app is opt-in (enable it in the installer or with `OWNSUITE_APP_*`). A common starting set of Docs + Drive runs on **4 GB minimum, 8 GB recommended, 2 vCPU**. Add more apps or the mailbox and step up as the tables below show.

## What to buy

| Profile                                | RAM (minimum) | RAM (recommended) | vCPU | Disk   |
| -------------------------------------- | ------------- | ----------------- | ---- | ------ |
| **Docs + Drive** (common starting set) | 4 GB          | 8 GB              | 2    | 40 GB  |
| **+ Grist, Projects**                  | 6 GB          | 10 GB             | 2–4  | +15 GB |
| **+ Mailbox** — messages               | 8 GB          | 12 GB             | 4    | +10 GB |
| **+ Meet** — video (LiveKit)           | 8 GB          | 12 GB             | 4    | +5 GB  |

- **Minimum** is the tight floor: it runs, but with little burst headroom — keep the swap the bootstrap configures. **Recommended** leaves room for first-boot migrations, upgrades (old + new pod briefly overlap), and traffic spikes.
- **Disk** assumes external EU S3 for object storage (the production default — files live off the box). **Add ~20 GB** if you run the in-cluster **Garage** store instead, plus the same again if you keep its off-site backup copy in-cluster.
- These are steady-state figures for a small non-profit (a few dozen users). Heavy concurrent editing or large mailboxes scale RAM up first.

## Where the numbers come from

Every workload OwnSuite deploys declares a CPU/memory **request** (its guaranteed floor) and a memory **limit** (its ceiling). The tables below are those declarations, summed from the charts (`helmfile template`). Recommended RAM ≈ the sum of memory **limits** for the profile, plus ~1 GB for the OS + K3s and a little headroom for the few upstream operator pods that run at their chart defaults.

### Per-app footprint

| Component                                                                    | Enabled   | CPU request | Memory request | Memory limit |
| ---------------------------------------------------------------------------- | --------- | ----------- | -------------- | ------------ |
| **Foundation** (Keycloak, PostgreSQL, Valkey, cert-manager + CNPG operators) | always on | ~0.4 vCPU   | ~1.4 GB        | ~2.8 GB      |
| **Docs** (backend, Celery, frontend, y-provider)                             | opt-in    | 0.25 vCPU   | 1.0 GB         | 2.5 GB       |
| **Drive** (backend, Celery, frontend)                                        | opt-in    | 0.15 vCPU   | 0.65 GB        | 1.4 GB       |
| **Grist**                                                                    | opt-in    | 0.1 vCPU    | 0.25 GB        | 1.0 GB       |
| **Projects**                                                                 | opt-in    | 0.1 vCPU    | 0.25 GB        | 0.75 GB      |
| **Mailbox** (backend, worker, frontend, 2× MTA)                              | opt-in    | 0.45 vCPU   | 1.15 GB        | 2.3 GB       |
| **Meet** (backend, Celery, frontend, LiveKit, Egress)                        | opt-in    | 0.9 vCPU    | 1.65 GB        | 4.8 GB       |
| **Garage** object store (only if not using external S3)                      | no        | 0.05 vCPU   | 0.13 GB        | 0.5 GB       |

With Docs, Drive, Grist, Projects and the mailbox enabled, the declared requests total **~1.5 vCPU / 4.7 GB** and the memory limits total **~11 GB** — which is why 12 GB is the recommended figure there. **Meet** is the heavy outlier: real-time media (LiveKit) and, during a recording, the headless-Chrome **Egress** are CPU- and RAM-hungry and also consume real network **bandwidth** that scales with concurrent participants. Its memory *limit* is high (~4.8 GB) but mostly headroom for Egress; treat Meet as its own step-up and size for **modest concurrency** — add capacity (and bandwidth) before hosting large meetings.

### Disk

| What                                                         | Size                  |
| ------------------------------------------------------------ | --------------------- |
| OS + K3s + container images                                  | ~20 GB                |
| PostgreSQL volume (`OWNSUITE_PG_STORAGE`, default 10 Gi)     | 10 GB                 |
| Grist documents PVC (`OWNSUITE_GRIST_STORAGE`, default 5 Gi) | 5 GB (if enabled)     |
| In-cluster Garage data (+ off-site copy if in-cluster)       | +10 GB each (if used) |

User files and mail blobs live in **object storage**, not on the disk, when you use external S3 — so the disk stays small and predictable.

## Notes

- **Full-text mail search is not enabled.** The mailbox can run an optional search engine (OpenSearch), but it's left off to save memory on a single server. If you turn it on, add **1–2 GB of RAM** for it.
- **Memory is capped, CPU is not.** Each app has a memory ceiling (so one app can't starve the others) but is free to use spare CPU — capping CPU would slow down queries and migrations.
- **Leave room for upgrades.** During an upgrade a new copy of an app may run briefly alongside the old one; the recommended figures cover that overlap.
