# Local Kubernetes workflow (kind). Run `make help` for the list.
IMAGE   ?= edgar-analyst:dev
CLUSTER ?= edgar
NS      ?= edgar
OVERLAY ?= deploy/k8s/overlays/kind

.PHONY: help kind-up image secret deploy ingest-logs reingest status port-forward logs kind-down metrics-server rollout-status history break-config break-image rollback fix-config resync load watch

help:  ## Show targets
	@grep -E "^[a-z-]+:.*##" $(MAKEFILE_LIST) | sed "s/:.*##/:/"

kind-up:  ## Create the local kind cluster
	kind create cluster --name $(CLUSTER) --config deploy/kind/cluster.yaml

image:  ## Build the image and load it into kind (no registry needed)
	docker build -t $(IMAGE) .
	kind load docker-image $(IMAGE) --name $(CLUSTER)

secret:  ## Create/update the edgar-secrets Secret from .env (never committed)
	kubectl create namespace $(NS) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NS) create secret generic edgar-secrets --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -

deploy:  ## Apply all manifests (starts the ingest Job and the API Deployment)
	kubectl apply -k $(OVERLAY)

ingest-logs:  ## Follow the ingest Job, then wait for it to complete
	kubectl -n $(NS) logs -f job/edgar-ingest
	kubectl -n $(NS) wait --for=condition=complete job/edgar-ingest --timeout=30m

reingest:  ## Re-run ingest (Jobs are immutable, so delete and re-apply)
	kubectl -n $(NS) delete job edgar-ingest --ignore-not-found
	kubectl apply -k $(OVERLAY)

status:  ## Pods, Jobs, volumes and services
	kubectl -n $(NS) get pods,jobs,pvc,svc

port-forward:  ## Reach the API at localhost:8000
	kubectl -n $(NS) port-forward svc/edgar-api 8000:80

logs:  ## Follow API logs
	kubectl -n $(NS) logs -f deploy/edgar-api

# ---- A4: rollouts, rollback and autoscaling ------------------------------------------
METRICS_SERVER ?= https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml

metrics-server:  ## Install metrics-server (needed by the HPA); kind needs --kubelet-insecure-tls
	kubectl apply -f $(METRICS_SERVER)
	kubectl -n kube-system patch deployment metrics-server --type=json \
	  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s

rollout-status:  ## Watch the current rollout (fails after progressDeadlineSeconds)
	kubectl -n $(NS) rollout status deploy/edgar-api --timeout=240s

history:  ## Revisions of the API Deployment
	kubectl -n $(NS) rollout history deploy/edgar-api

break-config:  ## Ship a bad config: new pod runs but never becomes Ready (points at an empty data dir)
	kubectl -n $(NS) annotate deploy/edgar-api kubernetes.io/change-cause="bad config: EDGAR_DATA_DIR points at an empty dir" --overwrite
	kubectl -n $(NS) set env deploy/edgar-api EDGAR_DATA_DIR=/tmp/empty-data

break-image:  ## Ship a tag that doesn't exist: new pod can't even start
	kubectl -n $(NS) annotate deploy/edgar-api kubernetes.io/change-cause="bad image tag" --overwrite
	kubectl -n $(NS) set image deploy/edgar-api api=edgar-analyst:does-not-exist

rollback:  ## Roll back one revision (or to a specific one: make rollback REV=3). Running it twice flips back!
	kubectl -n $(NS) annotate deploy/edgar-api kubernetes.io/change-cause="rollback$(if $(REV), to revision $(REV),)" --overwrite
	kubectl -n $(NS) rollout undo deploy/edgar-api $(if $(REV),--to-revision=$(REV),)
	@sleep 3  # let the controller observe the undo before reading rollout status
	kubectl -n $(NS) rollout status deploy/edgar-api --timeout=240s

fix-config:  ## Fix forward instead of rolling back: remove the bad env var from the live Deployment
	kubectl -n $(NS) set env deploy/edgar-api EDGAR_DATA_DIR-
	@sleep 3
	kubectl -n $(NS) rollout status deploy/edgar-api --timeout=240s

resync:  ## Re-apply the manifests (restores fields git manages, like the image; NOT env vars added by kubectl set)
	kubectl apply -k $(OVERLAY)

load:  ## Generate CPU load for the HPA (hits /readyz, which runs a vector-store lookup; no model calls)
	kubectl -n $(NS) run load --rm -it --restart=Never --image=busybox:1.36 -- \
	  /bin/sh -c 'while true; do wget -q -O- http://edgar-api/readyz >/dev/null; done'

watch:  ## Live view of pods and the autoscaler
	kubectl -n $(NS) get pods,hpa -w

kind-down:  ## Delete the cluster (and everything in it)
	kind delete cluster --name $(CLUSTER)
