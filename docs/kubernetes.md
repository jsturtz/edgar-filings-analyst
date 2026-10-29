# Running on Kubernetes

The agent runs on Kubernetes as two workloads that share one disk:

```
             ┌──────────── namespace: edgar ─────────────┐
 .env ──► Secret edgar-secrets      ConfigMap edgar-config
             │                              │
             ▼                              ▼
   Job edgar-ingest ──writes──► PVC edgar-data ◄──reads── Deployment edgar-api ◄── Service edgar-api ◄── port-forward :8000
   (runs once)                 (Chroma + SEC cache)        (probes: /healthz, /readyz)
```

## Quickstart (local, with kind)

Prerequisites: Docker, [kind](https://kind.sigs.k8s.io/) and `kubectl`. Write `.env` values
without quotes (`kubectl --from-env-file` keeps them literally).

```bash
make kind-up        # create a one-node cluster inside Docker
make image          # build the image and load it into the cluster
make secret         # create edgar-secrets from .env
make deploy         # apply the manifests: starts ingest and the API
make status         # watch: the API pod is Running but 0/1 Ready until ingest finishes
make ingest-logs    # follow ingest (the kind overlay ingests 4 companies, a few minutes)
make port-forward   # then, in another terminal:
curl localhost:8000/readyz
curl -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question": "What was Toro'"'"'s revenue in fiscal 2024?"}'
make kind-down      # delete everything
```

## What each manifest does

| File | Kind | Why it exists |
| --- | --- | --- |
| `namespace.yaml` | Namespace | Groups every resource for this app, so it can be listed or deleted as a unit. |
| `kustomization.yaml` (`configMapGenerator`) | ConfigMap | Non-secret settings (provider, model, data dir, ingest args) as environment variables. The generated name gets a content hash, so changing a setting rolls the pods automatically. |
| *(created by `make secret`)* | Secret | API keys from `.env`. Created from the command line and never committed. |
| `pvc.yaml` | PersistentVolumeClaim | A disk that survives pod restarts and redeploys. Ingest writes the index there; the API reads it. |
| `ingest-job.yaml` | Job | Runs to completion once, unlike a Deployment, which runs forever. Jobs are immutable, so re-running means delete and re-apply (`make reingest`). |
| `deployment.yaml` | Deployment | Keeps the API running. Its pod template has three probes (below), resource requests/limits, and Prometheus scrape annotations. |
| `service.yaml` | Service | A stable DNS name (`edgar-api.edgar.svc`) that load-balances across **Ready** API pods only. |

**Probes** (all in `deployment.yaml`):
- **startupProbe** (`/healthz`): allows up to about 150 s for the embedding model to load, before the other probes start.
- **livenessProbe** (`/healthz`): if the process stops responding, Kubernetes restarts the container. It deliberately doesn't check the model API, so an outage there doesn't cause restart loops.
- **readinessProbe** (`/readyz`): returns 503 until the index exists, so the Service sends no traffic to a pod that would give empty answers.

**Security:** pods run as non-root user 10001; `fsGroup` makes the volume writable by that user.

**Kustomize:** `base/` holds what's shared; `overlays/kind/` changes only what differs
locally (the image tag, `imagePullPolicy`, and a smaller ingest). A cloud overlay later
changes the image registry and storage class without copying the base.

## Debugging

| Symptom | Command | What to look for |
| --- | --- | --- |
| Pod stuck `Pending` | `kubectl -n edgar describe pod <pod>` | Events at the bottom: no node with enough memory, or the PVC not bound |
| `ImagePullBackOff` / `ErrImageNeverPull` | `kubectl -n edgar describe pod <pod>` | Image not loaded into kind: run `make image` |
| `CrashLoopBackOff` | `kubectl -n edgar logs <pod> --previous` | The Python traceback from the crashed run |
| Running but `0/1` Ready | `kubectl -n edgar logs deploy/edgar-api`, `curl localhost:8000/readyz` | Usually "vector index is empty": ingest hasn't finished |
| Anything else | `kubectl -n edgar get events --sort-by=.lastTimestamp` | Cluster-level timeline of what happened |

Notes: the API and the ingest Job share a `ReadWriteOnce` volume, which works because a kind
cluster has one node. On multi-node clusters, either schedule them together or have ingest
publish the index somewhere shared, like object storage or a vector database service.

## Rollouts, rollback and autoscaling

A Deployment never edits pods in place. Every change to the pod template (image, env,
resources) creates a **new ReplicaSet**, and the Deployment shifts pods from the old one to the
new one. Old ReplicaSets are kept (`revisionHistoryLimit: 5`), which is what makes rollback
instant. With `maxUnavailable: 0`, an old pod is only removed after a new pod is **Ready**,
so a bad release can't take the service down.

### How a bad deploy is contained (try it)

Open a second terminal with `make watch`, then:

```bash
make history          # revision 1: what you deployed in A3
make break-config     # new revision: same image, EDGAR_DATA_DIR points at an empty directory
make rollout-status   # waits... then reports the rollout has exceeded its progress deadline
make status           # two API pods: the OLD one 1/1 Ready, the NEW one Running 0/1
curl -X POST localhost:8000/ask ...   # still answers: the Service only routes to Ready pods
make rollback         # back to the previous revision; the broken pod is removed
make history          # the "bad config" revision is in the history, with its change-cause
```

**Gotcha:** `rollout undo` means "go back one revision," so running it twice flips you back
to the broken version. To be precise, roll back to a known-good number from `make history`:
`make rollback REV=<n>`. Two more quirks: rolling back *renumbers* (the restored revision gets a new number at the top, and its old number disappears), and CHANGE-CAUSE comes from an annotation on the Deployment, so it can carry over to the wrong revision. Verify with `kubectl -n edgar rollout history deploy/edgar-api --revision=<n>` before trusting a label. `make rollback` stamps its own change-cause to keep the history readable. Rolling back is the fast fix; **fixing forward** is the other option,
undoing the bad change itself in a new revision (`make fix-config`).

What you should see in `make watch`: the new pod starts, its readiness probe keeps returning
503 ("SEC cache ... is empty; run ingest"), the old pod is never terminated, and after 180 s
(`progressDeadlineSeconds`) the Deployment's `Progressing` condition turns false. That
condition is what a CI/CD pipeline watches to fail a deploy automatically.

`make break-image` is the other common failure: a tag that doesn't exist gives
`ErrImageNeverPull` or `ImagePullBackOff`. It's contained the same way, and recovered with `make rollback`.

`kubectl set env` and `kubectl set image` change the live cluster but not git, which is
*drift*. `kubectl apply` (`make resync`) restores fields the manifests manage, like the image
tag, but it won't remove an env var the manifests never mentioned, because apply only manages
the fields in its own configuration. That's why kubectl warns about rolling back a resource
"managed with kubectl apply." In a real team the manifests in git are the source of truth and
changes go through them (or a GitOps tool like Argo CD), not through `kubectl set`.

### Autoscaling

```bash
make metrics-server   # once per cluster: the HPA needs CPU metrics
kubectl -n edgar get hpa   # TARGETS shows current CPU vs. the 70% target (may say <unknown> for a minute)
make load             # in another terminal: hammers /readyz (vector-store lookups, no model calls)
make watch            # REPLICAS climbs toward 3 as CPU passes 70% of the 250m request
# stop `make load` (Ctrl-C); about a minute later it scales back to 1
```

The HPA targets a percentage of the **CPU request**, which is why every container needs
resource requests. The HPA is only in the kind overlay: on a multi-node cluster, extra API
pods couldn't share the `ReadWriteOnce` volume (see the note above).
