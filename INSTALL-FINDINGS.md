# First real install — findings log (Infomaniak external S3)

Tracking every gap/inconsistency hit during the first end-to-end install on
Infomaniak Public Cloud, so the docs can be updated for a **non-technical operator
to succeed solo, without AI**. Delete this file once folded into the docs.

**Status (this branch `fix/infomaniak-external-and-proxy`): all findings corrected in
the repo (code + docs) and validated.** Statically: terraform fmt/validate, helm lint,
kubeconform, ansible-lint, pytest, mkdocs --strict. Live, against the throwaway Infomaniak
deploy in garage mode: #12 (`terraform apply` created an S3-API bucket, visible via
`list_buckets`, then destroyed) and #20 (a presigned upload `PUT`→200 through the
same-origin Traefik proxy, `GET` returned the object). Live validation also surfaced **#21**
(the authenticated `/media/` download route was broken on Traefik for the same
portless-ExternalName reason), now fixed and validated.

Legend: ✅ done in repo (code) · 📘 done in repo (docs) · ✅🔬 done + live-validated

| # | Finding | Status | Fix landed |
|---|---|---|---|
| 1 | **Security-group egress 409.** Module re-declared allow-all egress, but Infomaniak Neutron auto-creates them → `SecurityGroupRuleExists`. | ✅ | Removed the explicit `egress_v4/v6` resources in `terraform/modules/infomaniak/main.tf` (commit C1). |
| 2 | **Application credential must be *unrestricted*.** A restricted app credential cannot mint the S3 EC2 credential → 403. | ✅📘 | `terraform.tfvars.example` + `provision.md` now require **Unrestricted** and explain why (C1/C5). |
| 3 | **External S3 keys had no injection path.** Apps read `s3-access`/`s3-secret`; only MTA secrets were wired. | ✅📘 | Wired `OWNSUITE_S3_ACCESS_KEY/SECRET`, `OWNSUITE_BACKUP_S3_*`, `OWNSUITE_RCLONE_CRYPT_PASSWORD` → `secretOverrides` (C3); documented in `configuration.md` (Secrets + Object storage) and `provision.md` (C5). |
| 4 | **External mode needs one bucket per app.** | 📘 | `provision.md` + `configuration.md` map enabled apps → buckets (`docs-/drive-/projects-/messages-media-storage`; Grist = PVC). In garage mode Terraform creates none (C5). |
| 5 | **`image_name` default wrong for Infomaniak.** Real image is `Debian 13 trixie`. | ✅📘 | Fixed module + env defaults; `provision.md` stresses the exact name (C1/C5). |
| 6 | **S3 region is `us-east-1`, not `eu-west`.** | ✅📘 | Module locals carry `us-east-1`; `provision.md`/`configuration.md` note it (C1/C5). |
| 7 | **1Password SSH agent breaks SSH/Ansible** (`Too many authentication failures`). | 📘 | `bootstrap.md` Caveats + `install.md` Troubleshooting document `IdentitiesOnly=yes` for Ansible and the tunnel (C5). |
| 8 | **Ansible callback `community.general.yaml` removed** in 12.0 → bootstrap aborts. | ✅ | `ansible.cfg`: `stdout_callback = default` + `result_format = yaml` (C2). |
| 9 | **Fetched kubeconfig lands in `ansible/kubeconfig`, not repo root.** | ✅📘 | Standardised on `ansible/kubeconfig`: gitignored, `suite`/Makefile point KUBECONFIG there, role default documented; `bootstrap.md` corrected (C2/C5). |
| 10 | **DNS: CAA tag + wildcard CNAME alternative undocumented.** | 📘 | `install.md`: CAA tag = `issue` ("specific hostnames"), not `issuewild`; offer `*.{domain}` CNAME → apex (C5). |
| 11 | **`suite install`/`sync` never sets `KUBECONFIG`** (relative path breaks helmfile). | ✅📘 | The SSH-tunnel context manager exports an absolute `KUBECONFIG=ansible/kubeconfig` (setdefault); Makefile default made absolute; docs note the export (C2/C5). |
| 12 | **🔴 Swift containers are NOT the S3 buckets.** Buckets created as Swift containers are invisible to the S3 endpoint. | ✅🔬📘 | Module creates buckets via the **S3 API** (aws provider against the Infomaniak S3 endpoint, minted EC2 creds); `bucket_names` defaults to `[]` since garage creates buckets in-cluster. `provision.md` drops the "Swift = S3" claim. **Live: `terraform apply` created a test bucket via the S3 API, confirmed visible via `list_buckets`, then destroyed.** |
| 13 | **🔴 boto3 aws-chunked checksum breaks all S3 writes** (`501 NotImplemented` on PutObject). | ✅ | `AWS_REQUEST/RESPONSE_CHECKSUM_*=when_required` on docs/drive/projects (C3). Add to messages when enabling Mailbox. |
| 14 | **Manual `helmfile sync` silently flips TLS to self-signed.** | 📘 | `configuration.md` warns to `export OWNSUITE_TLS_ISSUER=letsencrypt-http01` before any manual sync; `install.md` Troubleshooting too (C5). |
| 15 | **Docs `COLLABORATION_API_URL` path wrong → share/link-config 500.** | ✅ | Set to `/collaboration/api/` in `values/docs.yaml.gotmpl` (C3). |
| 16 | **🔴 Collaboration WebSocket 500 under Traefik** (service port 443 ⇒ TLS upstream). | ✅ | `yProvider.service.port: 80` + backend collaboration URLs on `:80` (C3). |
| 17 | **🔴 `/media/` broken under Traefik: ExternalName services refused.** | ✅📘 | The k3s role ships a `HelmChartConfig/traefik` with `allowExternalNameServices: true` into the auto-deploy manifests dir; `bootstrap.md` notes it + the SSRF trade-off (C2/C5). (Necessary but not sufficient — the ExternalName Service must also declare a port; see **#21**.) |
| 18 | **Grist blocks on the fresh-install setup gate** (`/boot`, asks for a boot key). | ✅ | `GRIST_IN_SERVICE: "true"` in `values/grist.yaml.gotmpl` (C3). |
| 19 | **🔴🔴 Infomaniak S3 has NO usable CORS → Drive browser uploads blocked.** | 📘 | **Decision: use `garage` mode on Infomaniak** (media same-origin, no CORS). `provision.md` Object-storage caveat + `configuration.md` tip document it (C5). |
| 19b | **Root cause: Swift `s3api` does not implement `PutBucketCors`** (OpenStack bug #2077629). | 📘 | Documented in the `provision.md` caveat; external-S3 reserved for CORS-capable RGW providers (C5). |
| 20 | **🔴🔴 Drive presigned URLs not wired for reverse-proxy.** | ✅🔬📘 | Drive's `AWS_S3_DOMAIN_REPLACE` signs presigned **uploads** against the public Drive host (path-style, same-origin); a new `drive-ingress` Ingress proxies `/{bucket}/` straight to the Garage ClusterIP Service preserving Host+path (no auth, no rewrite) so SigV4 still validates — backend keeps the internal endpoint (no hairpin). Gated to garage mode; documented in the `provision.md` caveat. **Live: presigned `PUT`→HTTP 200 through the public host, `GET` returned the object — SigV4 survives the Host-preserving proxy.** |
| 21 | **🔴 `/media/` download route also broken on Traefik** (found while validating #20). The upstream charts' `/media/` Ingress targets a `*-media` ExternalName Service with **no port**, which Traefik refuses ("service port not found") → `/media/` falls through to the frontend, so uploaded files / doc images never display. The k3s `allowExternalNameServices` flag (#17) is necessary but not sufficient; the chart exposes no port knob. | ✅🔬 | In garage mode, route `/media/` straight at the Garage ClusterIP Service (`garage:3900`) via a new Ingress in docs-ingress/drive-ingress — keeping the forwardAuth + rewrite middlewares — and disable the unroutable upstream media Ingress. **Live: `/media/` now reaches the backend media-auth instead of the frontend SPA; Traefik routers create with no port error.** |
