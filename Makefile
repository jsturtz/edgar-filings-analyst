# Local Kubernetes workflow (kind). Run `make help` for the list.
IMAGE   ?= edgar-analyst:dev
CLUSTER ?= edgar
NS      ?= edgar
OVERLAY ?= deploy/k8s/overlays/kind

.PHONY: help kind-up image secret deploy ingest-logs reingest status port-forward logs kind-down

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

kind-down:  ## Delete the cluster (and everything in it)
	kind delete cluster --name $(CLUSTER)
