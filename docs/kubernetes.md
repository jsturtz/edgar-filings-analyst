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
