# Cloud cost comparison — Scaleway vs Infomaniak

Evaluation for hosting a single production OwnSuite instance on **public cloud**
(compute instance + S3 object storage). VPS / dedicated offers are explicitly
out of scope. Prices were checked online in June 2026 — **re-confirm at purchase
time**, Infomaniak bills in CHF (EUR figures move with FX) and Scaleway raised
prices in June 2026.

## What we need to host (from `docs/operate/sizing.md`)

Single K3s node, two realistic profiles:

| Profile | vCPU | RAM | System disk | Object storage |
|---|---|---|---|---|
| **Core** (Docs + Drive) | 2 | 8 GB | ~40 GB | media bucket(s) + off-site backup |
| **All-in** (+ Grist, Projects, Mailbox) | 4 | 12–16 GB | ~50 GB | media bucket(s) + off-site backup |

Object storage holds app media (Docs/Drive/Projects/Mailbox uploads) plus the
backup target (Postgres WAL/PITR + rclone media sync). **Backups must live on a
different account/provider than the primary** (production rule, ADR-006) — so the
natural topology is *host on one provider, back up to the other*.

## Compute (instance) pricing

| Provider | Instance | vCPU / RAM | ~ EUR / month |
|---|---|---|---|
| **Infomaniak** | `a4-ram8-disk0` | 4 / 8 GB | **€10.59** |
| **Infomaniak** | `a4-ram16-disk0` | 4 / 16 GB | **~€16** |
| **Scaleway** | PLAY2-MICRO (cost-optimized) | 2 / 8 GB | ~€24 |
| **Scaleway** | DEV1-L (dev tier) | 4 / 8 GB | ~€31 |
| **Scaleway** | PRO2 / BASIC3 (production) 2 / 8 GB | 2 / 8 GB | ~€43 |
| **Scaleway** | DEV1-XL | 4 / 12 GB | ~€46 |
| **Scaleway** | BASIC3-X4C-16G (production) | 4 / 16 GB | ~€86 |

Infomaniak `diskN` flavors are diskless — attach a block volume (below).
**For equivalent RAM, Infomaniak compute is ~2–4× cheaper than Scaleway.**

## Storage pricing

| Item | Scaleway | Infomaniak |
|---|---|---|
| Block storage (system volume) | ~€0.095 /GB-mo | ~€0.092 /GB-mo (perf1) |
| Object storage (S3, standard) | €0.00803 /GB-mo (1-zone) · €0.01606 (multi-AZ) | ~€0.009 /GB-mo |
| Object storage free egress | 75 GB/mo, then €0.01/GB | **10 TB/mo**, then ~€0.008/GB |
| Instance egress | included in instance price | included |

Storage prices are effectively a wash. Infomaniak's object-storage egress
allowance is far larger, but at this scale neither is likely to bill egress.

## Total monthly estimate (compute + ~50 GB block + ~30 GB object)

| Profile | Scaleway | Infomaniak |
|---|---|---|
| **Core** | ~€28 (cost-opt) – €47 (prod) | **~€15** |
| **All-in** | ~€52 – €92 (prod) | **~€22** |

> S3 line item is ~€0.30–1.00/mo at this data volume on both — negligible vs compute.

**Verdict on cost: Infomaniak wins clearly on compute, the dominant line item.**
Scaleway is only competitive at its cost-optimized PLAY2 tier, and even then sits
above Infomaniak.

## Terraform implementation difficulty

The object-storage half is **identical and easy** for both: both are
S3-compatible, so a single shared sub-module using the `hashicorp/aws` provider
with an endpoint override (and EC2/S3 keys) creates buckets on either provider.

The compute/network half differs:

| | Scaleway | Infomaniak |
|---|---|---|
| Native TF provider | ✅ `scaleway/scaleway` (first-class) | ❌ none — it's **OpenStack** |
| What you use | one provider for instance + volume + flexible IP + security group + bucket | `terraform-provider-openstack/openstack` for instance/volume/network/router/floating-IP/secgroup + `aws` for the S3 bucket |
| Auth | API key (access/secret) | OpenStack application credentials / `clouds.yaml` + S3 EC2 creds |
| Networking | minimal | more verbose (explicit network/subnet/router/floating IP) |
| Docs / maturity | excellent | mature provider, but OpenStack-generic, more plumbing |
| Effort (standalone) | **Easy** (~1 day) | **Moderate** (~2–3 days) |

### Cost of "one module that supports both"

Terraform has no clean runtime provider switch — you cannot conditionally
instantiate a provider, and gating resources with `count`/`for_each` on a
`cloud = "..."` variable leaves both providers always required and dead resources
in every plan. **Recommended shape instead:**

```
modules/
  object-storage/     # shared, aws S3-compat, works for both
  host-scaleway/      # scaleway provider; outputs: ip, ssh, kubeconfig hooks
  host-infomaniak/    # openstack provider; same outputs
root/                 # picks one host-* module + object-storage
```

Same output contract on both `host-*` modules; the caller selects the provider by
which module it instantiates. This keeps each path simple and avoids the
all-providers-always-configured trap. Integration overhead beyond the two
standalone modules is small (~0.5 day) — the real work is the OpenStack path.

**Verdict on difficulty:** Scaleway is the easier provider by a wide margin
(native, less code). Infomaniak is the moderate one (OpenStack). Building *both*
is dominated by the Infomaniak/OpenStack path, not the integration.

## Bottom line for the decision

- **Cheapest host:** Infomaniak (~€15–22/mo all-in vs Scaleway ~€28–92).
- **Easiest Terraform:** Scaleway (native provider).
- **Backups need a *second* provider anyway** — so building both modules isn't
  either/or: the strong topology is **host on Infomaniak, back up to Scaleway
  Object Storage** (cheap, off-provider, satisfies ADR-006). That uses the cheap
  compute *and* the cheap/native S3, and means we build both sides regardless.

Sources: Scaleway [instances](https://www.scaleway.com/en/pricing/virtual-instances/) ·
[storage](https://www.scaleway.com/en/pricing/storage/) ·
Infomaniak [public-cloud prices](https://www.infomaniak.com/en/hosting/public-cloud/prices) ·
[object storage docs](https://docs.infomaniak.cloud/object_storage/) ·
[flavors](https://docs.infomaniak.cloud/compute/instances/flavors/).
</content>
</invoke>
