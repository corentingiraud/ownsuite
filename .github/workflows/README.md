# CI workflows

How continuous integration is wired for this repo: what each workflow proves,
when it runs, and which checks gate a merge.

## Design

- **Path-scoped triggers.** Every workflow declares `paths:` so a docs-only PR
  never boots a cluster, and an Ansible-only PR never runs the Helmfile checks.
- **Fast PR gates, heavy work nightly.** A PR is gated only by checks that can
  run in minutes. The expensive full-suite e2e (pulls ~15 images, 20–45 min) is
  proven on `main` and on the nightly schedule — never on a PR. See ADR-029.
- **Cancel stale PR runs.** Each PR-triggering workflow has a `concurrency`
  group keyed on `workflow + ref` with `cancel-in-progress` on `pull_request`
  events: a new push to a PR kills the in-flight run for that PR, so the queue
  isn't clogged by superseded runs. `main` / nightly runs (a distinct ref) are
  left to finish.
- **One source for the cluster CLIs.** helm / helmfile / kubeconform / k3d /
  kubectl are installed by the shared composite action
  [`.github/actions/setup-cluster-tools`](../actions/setup-cluster-tools/action.yml)
  (versions pinned there, tracked by Renovate; binaries cached per version).
  Pass `cluster: "true"` for jobs that stand up a k3d cluster.

## Workflows

| Workflow | What it proves | PR gate? | Other triggers |
|----------|----------------|----------|----------------|
| `ci` | Lint (ansible + python) and fast unit tests, then Molecule host-prep on Debian 12/13. No cluster. | **Yes** | push `main`, dispatch |
| `helmfile-ci` | Static Helmfile checks: `helm lint`, full `helmfile template`, kubeconform schema validation. | **Yes** | push `main`, dispatch |
| `helmfile-e2e` → `pvc-backup` | Isolated ADR-032 PVC backup → wipe → restore on a real k3d cluster (~4 min). | **Yes** | — |
| `helmfile-e2e` → `full` | Heavy full suite: `suite install` → Docs/Drive DoD → backup/restore. | No | schedule (04:00), push `main`, dispatch |
| `apps-e2e` | Per-app boot + definition-of-done, one app per fresh cluster (matrix). On a PR, only the changed app(s) run. | **Yes** (changed app only) | schedule (05:00), dispatch |
| `bootstrap-e2e` | Whole bootstrap incl. a real pinned K3s install → node Ready, Debian 12/13. | **Yes** (k3s role changes) | schedule (03:00), push `main`, dispatch |
| `docs` | Builds and deploys the MkDocs site to GitHub Pages. | No | push `main` (docs paths) |

PR gates fire only when the PR touches the matching `paths:`. A PR that changes
nothing under a workflow's paths is not gated by it.

## Adding / changing a workflow

- Need the cluster CLIs? Use the composite action — don't re-add the `curl`
  install block. Bump tool versions in the action (Renovate keeps them current).
- A new PR-triggering workflow should copy the `concurrency:` block from an
  existing one so stale PR runs get cancelled.
- Keep heavy, image-pulling, flake-prone jobs off the PR path; gate the PR on a
  fast isolated slice and re-prove the whole thing nightly / on `main`.
