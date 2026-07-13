# Production Model Runtime

The production Compose stack supports one model profile at a time. Both profiles run separate
llama.cpp servers for chat and embeddings on the internal Compose network; neither service
publishes a host port. The containers use pinned variants of the official
[llama.cpp server images](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md).

## Model Files

Store both GGUF files beneath one host directory and configure filenames relative to that
directory:

```env
MODEL_DIR=/absolute/path/to/models
LLM_MODEL_FILE=chat-model.gguf
EMBEDDING_MODEL_FILE=embedding-model.gguf
```

Compose mounts `MODEL_DIR` read-only at `/models`. Subdirectories are allowed in the filename
settings. Startup exits with status `2` and names the missing setting when a configured file is
absent or unreadable.

## CPU Profile

The production example selects `models-cpu` by default:

```env
COMPOSE_PROFILES=models-cpu
MODEL_CPU_THREADS=8
```

Adjust the thread count to the physical CPU capacity available to Docker. The CPU profile uses
the pinned `LLAMA_CPP_CPU_IMAGE` and does not require a GPU runtime.

## NVIDIA GPU Profile

Select the CUDA 13 image profile:

```env
COMPOSE_PROFILES=models-gpu
MODEL_GPU_LAYERS=99
```

The host must provide a working NVIDIA driver, Docker GPU access, and enough VRAM for the selected
quantizations and context sizes. Verify Docker GPU access before starting the application:

```bash
docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi
```

The GPU services request all visible GPUs and offload up to `MODEL_GPU_LAYERS`. Reduce the layer
count, context size, or model quantization if startup exhausts VRAM.

## Startup

Create `config/env/prod.env` from the example, replace its secrets and model filenames, then start the
selected profile with the normal production command:

```bash
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml up --build -d --wait
```

Inspect model startup and application readiness through:

```bash
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml ps
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml logs llm-cpu embedding-cpu
curl -fsS http://127.0.0.1:${WEB_PORT:-3000}/health/llm
curl -fsS http://127.0.0.1:${WEB_PORT:-3000}/health/embedding
```

Use `llm-gpu embedding-gpu` in the log command for the GPU profile.

## Host-Managed Servers

An operator may omit `COMPOSE_PROFILES` and point `LLM_BASE_URL` and `EMBEDDING_BASE_URL` at
separately managed OpenAI-compatible servers. Those endpoints must be reachable from the API and
worker containers. Keep their listener and firewall scope restricted to the deployment host or a
trusted internal network.
