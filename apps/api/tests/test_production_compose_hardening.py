from pathlib import Path

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "deploy" / "compose.prod.yaml"
RUNTIME_SERVICES = {
    "web",
    "api",
    "ingestion-worker",
    "redis",
    "postgres",
    "llm-cpu",
    "embedding-cpu",
    "llm-gpu",
    "embedding-gpu",
}


def load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_all_runtime_services_use_the_mandatory_security_baseline() -> None:
    services = load_compose()["services"]

    assert RUNTIME_SERVICES <= services.keys()
    for name in RUNTIME_SERVICES:
        service = services[name]
        assert service["read_only"] is True, name
        assert service["init"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["user"] not in {"0", "0:0", "root"}, name


def test_all_runtime_services_have_resource_and_log_bounds() -> None:
    services = load_compose()["services"]

    for name in RUNTIME_SERVICES:
        service = services[name]
        assert service["pids_limit"], name
        assert service["mem_limit"], name
        assert service["cpus"], name
        assert service["ulimits"]["nofile"]["soft"], name
        assert service["ulimits"]["nofile"]["hard"], name
        assert service["logging"]["driver"] == "json-file", name
        assert service["logging"]["options"]["max-size"], name
        assert service["logging"]["options"]["max-file"], name


def test_writable_mounts_are_explicit_and_model_mounts_are_read_only() -> None:
    services = load_compose()["services"]

    assert services["api"]["volumes"] == ["api_storage:/app/storage"]
    assert services["ingestion-worker"]["volumes"] == ["api_storage:/app/storage"]
    assert services["redis"]["volumes"] == ["redis_data:/data"]
    assert services["postgres"]["volumes"] == [
        "postgres_data:/var/lib/postgresql/data"
    ]

    for name in {"llm-cpu", "embedding-cpu", "llm-gpu", "embedding-gpu"}:
        assert services[name]["volumes"] == [
            "${MODEL_DIR:-../var/models}:/models:ro"
        ]

    for name in RUNTIME_SERVICES:
        tmpfs_targets = {mount.split(":", maxsplit=1)[0] for mount in services[name]["tmpfs"]}
        assert "/tmp" in tmpfs_targets, name


def test_gpu_services_reserve_a_bounded_number_of_devices() -> None:
    services = load_compose()["services"]

    for name in {"llm-gpu", "embedding-gpu"}:
        devices = services[name]["deploy"]["resources"]["reservations"]["devices"]
        assert devices == [
            {
                "driver": "nvidia",
                "count": "${MODEL_GPU_COUNT:-1}",
                "capabilities": ["gpu"],
            }
        ]


def test_embedding_services_accept_the_configured_document_chunk_window() -> None:
    services = load_compose()["services"]

    for name in {"embedding-cpu", "embedding-gpu"}:
        command = services[name]["command"][0]
        assert '--batch-size "${EMBEDDING_SERVER_BATCH_SIZE:-2048}"' in command
        assert '--ubatch-size "${EMBEDDING_SERVER_UBATCH_SIZE:-2048}"' in command


def test_application_images_declare_non_root_users() -> None:
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    web_dockerfile = (ROOT / "apps" / "web" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "\nUSER 10001:10001\n" in api_dockerfile
    assert "\nUSER 101:101\n" in web_dockerfile
