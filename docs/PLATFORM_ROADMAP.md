# Platform roadmap: Kubernetes, multicloud models, Terraform

This plan takes the EDGAR agent from "runs on my laptop" to "runs as a monitored service on
Kubernetes, on any of three clouds' model APIs, on infrastructure defined in Terraform".

It is written for **Claude Code working with Jordan** in this repo. Jordan's goals are to
learn Kubernetes, the major cloud platforms and Terraform hands-on, and to be able to explain
every piece in an interview. So the plan is deliberately incremental: **one step = one
reviewed commit**.

---

## How to work through this plan (read first)

1. **Do exactly one step at a time.** Do not start the next step until Jordan says so.
2. **At the end of each step, stop and post a checkpoint** containing:
   - what changed (files + a one-line reason for each)
   - the acceptance checks you ran and their output (or what Jordan needs to run, if a check
     needs his credentials)
   - **"What you just learned"**: 3–6 short bullets explaining the new concepts in plain
     language, tied to the files in this step
   - **"Interview questions"**: 2–3 questions an interviewer might ask about this step, with
     short answers
   - the proposed commit message
3. **Commit only after Jordan approves**, as a single commit for that step, using the
   message from the checkpoint (imperative subject, body explaining *why*). Then push.
4. **Never commit secrets.** API keys live in `.env` (gitignored) or Kubernetes Secrets
   created from the command line. Terraform state (`*.tfstate`) is gitignored.
5. **Never create paid cloud resources without explicit approval.** Before any
   `terraform apply` or cloud CLI call that creates resources, show the plan, an estimated
   hourly/daily cost, and the exact teardown command, then wait for a "go".
6. **Keep the existing unit tests passing** (`uv run pytest`) and add tests for new pure
   logic. Keep the CI workflow green.
7. **Don't re-run the full 149-question eval** (it costs about $7). Use
   `--systems agent --limit 10` (or `--limit 20`) for anything new.
8. Library APIs move fast (this project already hit breaking changes in
   `claude-sonnet-5-5`). **Check current docs** for any new library or cloud API before
   writing code against it, and say which docs you checked.

### Prerequisites on Jordan's machine

Docker, `kind`, `kubectl` (includes Kustomize via `kubectl apply -k`), `terraform`, and the
cloud CLIs as each part needs them: `az` (Parts B and C), `aws` and `gcloud` (Part B). Check
for each at the start of the step that needs it, and give install commands if missing.

---

## Step 0: Commit the published eval results

The README's results table (149 questions: agent 99% vs. baseline 47%) should be backed by
the raw run in the repo.

- Find the full run in `results/` (the `summary_*.md` whose table matches the README, plus
  its `run_*.jsonl`). Commit only that pair plus any small smoke runs worth keeping, not
  every experiment.
- Link it from the README's Results section ("raw results: `results/run_<stamp>.jsonl`").
- Check the files for anything sensitive before committing. They should contain only
  questions, answers and grades.

**Acceptance:** `uv run python eval/run_eval.py --summarize results/run_<stamp>.jsonl`
reproduces the README tables.

---

## Part A: Run the agent on Kubernetes (local, free)

### A1. Serve the agent as a FastAPI service with health checks and metrics

Kubernetes needs a process with an HTTP API, health endpoints and metrics. `langgraph dev`
is a development server, so add a small production-style service instead.

- `src/edgar_agent/api.py`: FastAPI app
  - `POST /ask` with `{"question": "..."}` → the `AgentAnswer` JSON plus `grounded`,
    `grounding_reason` and `tool_calls`
  - `GET /healthz`: liveness. The process is up; no external calls.
  - `GET /readyz`: readiness. Settings load, the Chroma collection exists and is non-empty,
    and companyfacts cache is present. Returns 503 otherwise, so Kubernetes holds traffic
    until ingest has run.
  - `GET /metrics`: Prometheus metrics via `prometheus-client`: request count by status,
    request latency histogram, a grounded/ungrounded counter, a tool-calls-per-question
    histogram, and a counter by LLM provider.
  - Build the graph once at startup (lifespan), not per request.
- Dependencies: `fastapi`, `uvicorn[standard]`, `prometheus-client`.
- Tests: `tests/test_api.py` using FastAPI's `TestClient` with the graph and readiness
  checks injected/faked (no model calls), covering `/healthz`, `/readyz` 503 vs 200,
  `/ask` response shape, and that `/metrics` exposes the counters.
- README: a "Run as an API" snippet (`uv run uvicorn edgar_agent.api:app`).

**Acceptance:** tests pass; locally, `curl localhost:8000/healthz` → 200;
`curl -X POST localhost:8000/ask -d '{"question": "What was Toro'"'"'s revenue in fiscal 2024?"}' -H 'content-type: application/json'`
returns a grounded answer.

### A2. Containerize it

- `Dockerfile`, multi-stage:
  - Install **CPU-only PyTorch** (from the PyTorch CPU index) so the image isn't 5+ GB;
    the embedding model is small and runs fine on CPU.
  - Install the project's locked dependencies with `uv` (no dev dependencies).
  - Pre-download the embedding model at build time, so pods don't fetch it from Hugging
    Face at startup.
  - Run as a non-root user; `EXPOSE 8000`; `CMD` runs uvicorn.
  - The same image runs the ingest job (different command), so there's one image to build
    and ship.
- `.dockerignore`: `.venv`, `data/`, `.env`, `results/`, `.git`, caches.

**Acceptance:** `docker build -t edgar-analyst:dev .` succeeds. Report the image size
(target: under ~2.5 GB). `docker run --env-file .env -v $PWD/data:/app/data -p 8000:8000 edgar-analyst:dev`,
and `/readyz` returns 200 using the existing local data.

### A3. Deploy to a local kind cluster with Kustomize

- `deploy/kind/cluster.yaml`: single-node kind cluster, with a port mapping if useful.
- `deploy/k8s/base/` (Kustomize):
  - `namespace.yaml`: `edgar`
  - `configmap.yaml`: non-secret settings (`LLM_PROVIDER`, `ANTHROPIC_MODEL`,
    `EDGAR_DATA_DIR=/data`, `RETRIEVAL_TOP_K`)
  - `pvc.yaml`: one `PersistentVolumeClaim` for `/data` (Chroma index + SEC cache)
  - `ingest-job.yaml`: a `Job` that runs `python -m edgar_agent.ingest` and
    `eval/build_golden.py` into the PVC
  - `deployment.yaml`: the API, mounting the PVC, env from the ConfigMap and a Secret
    named `edgar-secrets`, liveness on `/healthz`, readiness on `/readyz`, CPU/memory
    requests and limits sized for the embedding model, and Prometheus scrape annotations
  - `service.yaml`: ClusterIP on port 80 → 8000
  - `kustomization.yaml`
- `deploy/k8s/overlays/kind/`: uses the locally loaded image tag with
  `imagePullPolicy: IfNotPresent`.
- The Secret is created from `.env`, not committed:
  `kubectl -n edgar create secret generic edgar-secrets --from-env-file=.env`
- `Makefile` targets: `kind-up`, `image` (build + `kind load docker-image`), `secret`,
  `deploy` (`kubectl apply -k deploy/k8s/overlays/kind`), `ingest` (run and wait for the
  Job), `port-forward`, `logs`, `kind-down`.
- `docs/kubernetes.md`: what each manifest does and why, how to run, how to debug
  (`kubectl describe`, `kubectl logs`, `kubectl get events`).

**Acceptance:** `make kind-up image secret deploy ingest`, then the API pod is
`Running` and `Ready` (it should be *not Ready* until ingest completes; show that). Then
`make port-forward` and the `/ask` curl from A1 works through the cluster.

### A4. Operate it: rollouts, rollback and scaling

- A `HorizontalPodAutoscaler` on CPU (the kind overlay may need `metrics-server`; include
  the install command in the Makefile or docs).
- Document and demonstrate a rolling update and a rollback:
  `kubectl rollout status`, `kubectl rollout history`, `kubectl rollout undo`.
  Deliberately ship a broken image tag, watch the readiness probe stop the rollout, then
  roll back.
- Add to `docs/kubernetes.md`: "how a bad deploy is contained," which explains readiness
  gates, `maxUnavailable` and rollback.

**Acceptance:** the HPA shows targets; the broken-rollout demo leaves the old pods serving
traffic, and `rollout undo` recovers.

---

## Part B: Multicloud model providers (cheap, a few dollars)

The agent already supports `anthropic` and `azure_openai` through `src/edgar_agent/llm.py`.
Extend that so one agent and one golden set run on all three major clouds' model services.

### B1. Add AWS Bedrock and Google Vertex AI providers

- `LLM_PROVIDER` gains `bedrock` and `vertex`.
  - Bedrock: LangChain's AWS integration (`langchain-aws`, the Converse-API chat model).
    The model ID comes from env (e.g. a Claude, Nova or Llama model available in the
    account's region). Auth uses the standard AWS credential chain.
  - Vertex AI: LangChain's Google integration for Vertex (check current docs: Google has
    been consolidating its LangChain packages). Gemini model from env. Auth uses
    Application Default Credentials (`gcloud auth application-default login`), with
    project and region from env.
- Make the cloud SDKs **optional extras** in `pyproject.toml` (`aws`, `gcp`), so the base
  install stays lean. `llm.py` imports them lazily.
- `structured_output_method()`: keep native JSON schema for Anthropic and use tool or
  function calling where that is the most reliable option. Verify per provider.
- `messages.strip_thinking_blocks`: also strip any provider-specific reasoning block types
  (e.g. Bedrock's `reasoning_content`) that would break the finalize call.
- `.env.example` and the README "Model providers" section: the new variables.
- Tests: config/provider selection (pure, no network), like `tests/test_llm_config.py`.

**Acceptance:** unit tests pass. With credentials, Jordan runs one `ask` per provider.
Show each answer and grounding result.

### B2. Compare providers on the same golden set

- Record `provider` and `model` on every row in `run_eval.py`.
- `eval/compare_runs.py`: reads several `results/run_*.jsonl` files and prints one
  markdown table (accuracy by tier and type, grounding rate, average latency, average tool
  calls), one column per provider/model. It makes **no model calls**.
- Run `--systems agent --limit 20` (or a fixed, representative `--tiers` slice) on each
  provider. Cost: about $1 or less per provider with small models.
- README: a "Multicloud comparison" table with honest caveats (small sample, different
  model sizes).

**Acceptance:** one comparison table covering Anthropic, Azure OpenAI, Bedrock and Vertex,
generated from saved runs.

---

## Part C: Infrastructure as code with Terraform (Azure AKS)

Azure, because Jordan is already setting up an Azure account for Azure OpenAI, and AKS has a
free control-plane tier, so the cost is mostly one small VM for a few hours.

### C1. Terraform for AKS + container registry (+ optional Azure OpenAI)

- `infra/azure/`: `versions.tf` (pinned `azurerm` provider), `variables.tf`, `main.tf`,
  `outputs.tf`, `terraform.tfvars.example`:
  - resource group
  - Azure Container Registry (Basic SKU)
  - AKS cluster: free tier, one small system node pool (start with the smallest size that
    meets AKS minimums and fits the embedding model; make it a variable)
  - `AcrPull` role assignment so the cluster can pull from the registry
  - optional, behind `create_openai = false`: Azure OpenAI account + a small model
    deployment. Check current model names and versions available in the chosen region.
  - outputs: registry login server, `az aks get-credentials` command, Azure OpenAI
    endpoint if created
- `.gitignore`: `.terraform/`, `*.tfstate*`, `*.tfvars` (keep the `.example`).
- `docs/terraform.md`: what each resource is, `init/plan/apply/destroy`, what state is
  and why it's not committed, and a cost table.

**Acceptance:** `terraform fmt -check`, `terraform validate` and `terraform plan` succeed.
**Stop here and post the plan summary, a cost estimate and the teardown command. Do not
apply without Jordan's "go".**

### C2. Deploy to AKS, verify, tear down

- `deploy/k8s/overlays/aks/`: image from the registry, AKS's default storage class,
  `imagePullPolicy: Always`.
- Makefile targets: `aks-credentials`, `acr-push`, `aks-deploy`, `aks-ingest`,
  `aks-destroy` (wraps `terraform destroy`).
- Run it for real: apply, push, deploy, ingest, `/ask` through a port-forward (no public
  ingress needed), capture `kubectl get pods` and a sample answer for the README, then
  **destroy everything the same day** and confirm in the Azure portal that the resource
  group is gone.
- `docs/cloud-deploy.md`: the exact sequence, what it cost, and lessons learned.

**Acceptance:** the agent answered a question running on AKS; `terraform destroy`
completed; the README has a short "Deployed on AKS" note with the captured output.

### C3. Wrap-up

- Update the README: architecture diagram (add the API, Kubernetes, Terraform and
  providers), layout section, and roadmap.
- Post a final checkpoint with suggested resume bullets for the new skills (Kubernetes,
  Terraform, Azure, AWS Bedrock, GCP Vertex AI, Prometheus metrics), stated only at the
  level actually done.
