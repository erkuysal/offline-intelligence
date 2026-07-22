#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent
API_PATH = ROOT / "apps" / "api"


def configure_import_path() -> None:
    api_path = str(API_PATH)
    if api_path not in sys.path:
        sys.path.insert(0, api_path)

    current_pythonpath = os.environ.get("PYTHONPATH")
    if current_pythonpath:
        paths = current_pythonpath.split(os.pathsep)
        if api_path not in paths:
            os.environ["PYTHONPATH"] = os.pathsep.join([api_path, current_pythonpath])
    else:
        os.environ["PYTHONPATH"] = api_path

    app_module = sys.modules.get("app")
    if app_module is not None and not hasattr(app_module, "__path__"):
        del sys.modules["app"]


def run_subprocess(
    args: Sequence[str],
    cwd: Path = ROOT,
    environment: Mapping[str, str] | None = None,
) -> int:
    return subprocess.call(args, cwd=cwd, env=environment)


def load_root_env(profile: str = "development") -> Path | None:
    configure_import_path()

    from app.env_files import load_env_file

    return load_env_file(profile)


def runserver(_args: argparse.Namespace) -> int:
    configure_import_path()

    from app.main import main

    main()
    return 0


def migrate(_args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()
    return run_subprocess(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=API_PATH,
    )


def build_test_environment() -> dict[str, str]:
    from sqlalchemy.engine import make_url

    load_root_env("test")
    configured_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL or TEST_DATABASE_URL must be configured")

    database_url = make_url(configured_url)
    database_name = database_url.database or ""
    if not database_name:
        raise RuntimeError("The configured test database URL must include a database name")
    if not database_name.endswith("_test"):
        database_url = database_url.set(database=f"{database_name}_test")

    admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        admin_url = database_url.set(
            drivername=database_url.drivername.split("+", 1)[0],
            database="postgres",
        ).render_as_string(hide_password=False)

    environment = os.environ.copy()
    environment.update(
        {
            "ENVIRONMENT": "testing",
            "DATABASE_URL": database_url.render_as_string(hide_password=False),
            "TEST_DATABASE_ADMIN_URL": admin_url,
            "DOCUMENT_STORAGE_DIR": os.environ.get(
                "TEST_DOCUMENT_STORAGE_DIR",
                "/tmp/offline-intelligence-hub-tests/documents",
            ),
            "DOCUMENT_INGESTION_MODE": "sync",
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "EMBEDDING_BACKEND": "fake",
            "EMBEDDING_MODEL": "fake-bow",
            "RERANKER_BACKEND": "disabled",
            "QUERY_REWRITE_BACKEND": "disabled",
        }
    )
    return environment


def build_e2e_environment() -> dict[str, str]:
    from sqlalchemy.engine import make_url

    load_root_env("e2e")
    configured_url = os.environ.get("E2E_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL or E2E_DATABASE_URL must be configured")

    database_url = make_url(configured_url)
    database_name = database_url.database or ""
    if not database_name:
        raise RuntimeError("The configured E2E database URL must include a database name")
    if not database_name.endswith("_e2e"):
        database_url = database_url.set(database=f"{database_name}_e2e")

    admin_url = os.environ.get("E2E_DATABASE_ADMIN_URL")
    if not admin_url:
        admin_url = database_url.set(
            drivername=database_url.drivername.split("+", 1)[0],
            database="postgres",
        ).render_as_string(hide_password=False)

    environment = os.environ.copy()
    environment.update(
        {
            "ENVIRONMENT": "testing",
            "DATABASE_URL": database_url.render_as_string(hide_password=False),
            "E2E_DATABASE_ADMIN_URL": admin_url,
            "DOCUMENT_STORAGE_DIR": os.environ.get(
                "E2E_DOCUMENT_STORAGE_DIR",
                "/tmp/offline-intelligence-hub-e2e/documents",
            ),
            "DOCUMENT_INGESTION_MODE": "sync",
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "EMBEDDING_BACKEND": "fake",
            "EMBEDDING_MODEL": "fake-bow",
            "RERANKER_BACKEND": "disabled",
            "QUERY_REWRITE_BACKEND": "disabled",
        }
    )
    return environment


def e2e_setup(_args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_e2e_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"E2E setup failed: {exc}", file=sys.stderr)
        return 2

    prepare_status = run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "e2e" / "environment.py"), "setup"],
        environment=environment,
    )
    if prepare_status != 0:
        return prepare_status
    return run_subprocess(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=API_PATH,
        environment=environment,
    )


def e2e_cleanup(_args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_e2e_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"E2E cleanup failed: {exc}", file=sys.stderr)
        return 2
    return run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "e2e" / "environment.py"), "cleanup"],
        environment=environment,
    )


def test(args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_test_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"Test setup failed: {exc}", file=sys.stderr)
        return 2

    prepare_status = run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "db" / "prepare-test.py")],
        environment=environment,
    )
    if prepare_status != 0:
        return prepare_status

    migration_status = run_subprocess(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=API_PATH,
        environment=environment,
    )
    if migration_status != 0:
        return migration_status

    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    command = [sys.executable, "-m", "pytest"]
    if pytest_args:
        command.extend(pytest_args)
    else:
        command.append("-q")
    return run_subprocess(command, environment=environment)


def test_container(_args: argparse.Namespace) -> int:
    return run_subprocess(
        ["docker", "compose", "-f", "deploy/compose.yaml", "run", "--build", "--rm", "api-tests"]
    )


def lint(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "ruff", "check", "."])


def typecheck(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "mypy", "apps/api/app"])


def smoke(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "smoke.sh")])


def llm_probe(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.schemas.chat import ChatCompletionRequest, ChatMessage
    from app.services.llm import LLMError, get_llm_backend

    request = ChatCompletionRequest(
        messages=[
            ChatMessage(role="user", content=args.prompt),
        ],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    try:
        response = get_llm_backend().complete_chat(request)
    except LLMError as exc:
        print(f"LLM probe failed: {exc}", file=sys.stderr)
        return 1

    print(response.choices[0].message.content)
    return 0


def llm_start(args: argparse.Namespace) -> int:
    environment = os.environ.copy()
    if args.profile:
        environment["LLAMA_PROFILE"] = args.profile
    return subprocess.call(
        ["bash", str(ROOT / "scripts" / "models" / "start-llm.sh")],
        cwd=ROOT,
        env=environment,
    )


def llm_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "check-llm.sh")])


def llm_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "stop-llm.sh")])


def embedding_start(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "start-embedding.sh")])


def embedding_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "check-embedding.sh")])


def embedding_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "stop-embedding.sh")])


def reranker_start(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "start-reranker.sh")])


def reranker_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "check-reranker.sh")])


def reranker_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "stop-reranker.sh")])


def embedding_reindex(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.services.embeddings import (
        EmbeddingError,
        get_embedding_provider,
        reembed_all_document_chunks,
    )

    settings = get_settings()
    try:
        with SessionLocal() as db:
            processed = reembed_all_document_chunks(
                db,
                provider=get_embedding_provider(),
                batch_size=settings.embedding_reindex_batch_size,
                stale_only=args.stale_only,
            )
    except EmbeddingError as exc:
        print(f"Embedding reindex failed: {exc}", file=sys.stderr)
        return 1

    qualifier = "stale " if args.stale_only else ""
    print(f"Re-embedded {processed} {qualifier}document chunks with {settings.embedding_model}")
    return 0


def evaluate_retrieval(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.evaluation.retrieval import (
        EvaluationThresholds,
        build_database_retriever,
        evaluate_dataset,
        format_summary,
        load_dataset,
        prepare_corpus,
        write_report,
    )
    from app.services.embeddings import EmbeddingError, get_embedding_provider
    from app.retrieval import (
        DenseRetrievalStrategy,
        LexicalRetrievalStrategy,
        build_retrieval_strategy,
    )
    from app.retrieval.contracts import RetrievalStrategy

    try:
        dataset = load_dataset(Path(args.dataset))
        provider = (
            get_embedding_provider()
            if args.strategy in {"dense", "hybrid", "reranked", "multi_query"}
            else None
        )
        if (
            provider is not None
            and dataset.manifest.embedding_model != provider.model
            and not args.allow_model_mismatch
        ):
            raise ValueError(
                f"Dataset requires embedding model {dataset.manifest.embedding_model!r}; "
                f"configured model is {provider.model!r}. Use --allow-model-mismatch only for experiments."
            )
        settings = get_settings()
        strategy: RetrievalStrategy
        if args.strategy == "dense" and provider is not None:
            strategy = DenseRetrievalStrategy(provider)
        elif args.strategy in {"hybrid", "reranked", "multi_query"} and provider is not None:
            strategy = build_retrieval_strategy(args.strategy, provider=provider, settings=settings)
        else:
            strategy = LexicalRetrievalStrategy()
        thresholds = EvaluationThresholds(
            min_recall_at_k=args.min_recall,
            min_precision_at_k=args.min_precision,
            min_mean_reciprocal_rank=args.min_mrr,
            min_hit_rate=args.min_hit_rate,
            min_no_result_accuracy=args.min_no_result_accuracy,
            max_mean_latency_ms=args.max_mean_latency_ms,
            max_p95_latency_ms=args.max_p95_latency_ms,
            max_authorization_leaks=args.max_authorization_leaks,
        )
        with SessionLocal() as db:
            user_id, key_by_document_id, id_by_document_key = prepare_corpus(
                db,
                dataset,
                provider=provider,
                settings=settings,
            )
            report = evaluate_dataset(
                dataset,
                retrieve=build_database_retriever(
                    db,
                    user_id=user_id,
                    strategy=strategy,
                    key_by_document_id=key_by_document_id,
                    id_by_document_key=id_by_document_key,
                ),
                retrieval_limit=args.limit,
                thresholds=thresholds,
                embedding_model=(
                    provider.model if provider is not None else dataset.manifest.embedding_model
                ),
                retrieval_strategy=strategy.name,
                max_context_chars=settings.rag_max_context_chars,
                max_context_chars_per_document=settings.rag_max_context_chars_per_document,
                reranker_model=(settings.reranker_model if args.strategy == "reranked" else None),
                reranker_model_revision=(
                    settings.reranker_model_revision if args.strategy == "reranked" else None
                ),
                query_rewrite_model=(
                    settings.query_rewrite_model if args.strategy == "multi_query" else None
                ),
                query_rewrite_model_revision=(
                    settings.query_rewrite_model_revision
                    if args.strategy == "multi_query"
                    else None
                ),
            )
        write_report(report, Path(args.output))
    except (EmbeddingError, OSError, ValueError) as exc:
        print(f"Retrieval evaluation failed: {exc}", file=sys.stderr)
        return 2

    print(format_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def evaluate_generation(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.evaluation.generation import (
        GenerationThresholds,
        evaluate_generation_dataset,
        format_generation_summary,
        write_generation_report,
    )
    from app.evaluation.retrieval import load_dataset, prepare_corpus
    from app.retrieval import DenseRetrievalStrategy
    from app.services.embeddings import EmbeddingError, get_embedding_provider
    from app.services.llm import LLMError, get_llm_backend

    try:
        dataset = load_dataset(Path(args.dataset))
        settings = get_settings()
        provider = get_embedding_provider() if args.mode in {"base_rag", "adapter_rag"} else None
        if (
            provider is not None
            and dataset.manifest.embedding_model != provider.model
            and not args.allow_model_mismatch
        ):
            raise ValueError(
                f"Dataset requires embedding model {dataset.manifest.embedding_model!r}; "
                f"configured model is {provider.model!r}."
            )
        thresholds = GenerationThresholds(
            min_parse_success_rate=args.min_parse_success,
            min_expected_fact_coverage=args.min_fact_coverage,
            min_citation_accuracy=args.min_citation_accuracy,
            min_citation_coverage=args.min_citation_coverage,
            min_answer_faithfulness=args.min_faithfulness,
            max_hallucination_rate=args.max_hallucination,
            min_refusal_accuracy=args.min_refusal_accuracy,
            max_restricted_fact_leaks=args.max_restricted_fact_leaks,
            max_mean_time_to_first_token_ms=args.max_mean_ttft_ms,
            max_p95_time_to_first_token_ms=args.max_p95_ttft_ms,
            max_mean_end_to_end_latency_ms=args.max_mean_latency_ms,
            max_p95_end_to_end_latency_ms=args.max_p95_latency_ms,
            min_mean_tokens_per_second=args.min_tokens_per_second,
        )
        if provider is None:
            report = evaluate_generation_dataset(
                dataset,
                db=None,
                user_id=None,
                strategy=None,
                backend=get_llm_backend(),
                settings=settings,
                thresholds=thresholds,
                retrieval_limit=args.limit,
                id_by_document_key=None,
                evaluation_mode=args.mode,
            )
        else:
            with SessionLocal() as db:
                user_id, _, id_by_document_key = prepare_corpus(
                    db,
                    dataset,
                    provider=provider,
                    settings=settings,
                )
                report = evaluate_generation_dataset(
                    dataset,
                    db=db,
                    user_id=user_id,
                    strategy=DenseRetrievalStrategy(provider),
                    backend=get_llm_backend(),
                    settings=settings,
                    thresholds=thresholds,
                    retrieval_limit=args.limit,
                    id_by_document_key=id_by_document_key,
                    evaluation_mode=args.mode,
                )
        write_generation_report(report, Path(args.output))
    except (EmbeddingError, LLMError, OSError, ValueError) as exc:
        print(f"Generation evaluation failed: {exc}", file=sys.stderr)
        return 2

    print(format_generation_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def build_training_evaluation_matrix(args: argparse.Namespace) -> int:
    configure_import_path()

    from app.evaluation.adaptation import (
        EvaluationMode,
        TaskThresholds,
        build_adaptation_evaluation_report,
        format_adaptation_summary,
        load_generation_report,
        write_adaptation_report,
    )
    from app.evaluation.generation import GenerationReport

    try:
        reports: Mapping[EvaluationMode, GenerationReport] = {
            "base": load_generation_report(Path(args.base)),
            "base_rag": load_generation_report(Path(args.base_rag)),
            "adapter": load_generation_report(Path(args.adapter)),
            "adapter_rag": load_generation_report(Path(args.adapter_rag)),
        }
        regression_reports: Mapping[
            Literal["base_rag", "adapter_rag"], GenerationReport
        ] = {
            "base_rag": load_generation_report(Path(args.base_rag_regression)),
            "adapter_rag": load_generation_report(Path(args.adapter_rag_regression)),
        }
        report = build_adaptation_evaluation_report(
            reports,
            regression_reports=regression_reports,
            task_thresholds=TaskThresholds(
                min_language_adherence=args.min_language_adherence,
                min_citation_format_validity=args.min_citation_format_validity,
                min_json_schema_validity=args.min_json_schema_validity,
                min_incident_report_structure=args.min_incident_report_structure,
                min_terminology_consistency=args.min_terminology_consistency,
                min_supported_refusal=args.min_supported_refusal,
            ),
            gated_modes=tuple(args.gate_mode or ("adapter_rag",)),
        )
        write_adaptation_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Adaptation evaluation matrix failed: {exc}", file=sys.stderr)
        return 2

    print(format_adaptation_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def build_training_evaluation_index(args: argparse.Namespace) -> int:
    from training.evaluation_evidence import (
        build_evaluation_evidence_index,
        write_evaluation_evidence_index,
    )

    try:
        report = build_evaluation_evidence_index(
            dataset_validation_path=Path(args.dataset_validation),
            training_run_path=Path(args.training_run),
            held_out_behavior_path=Path(args.held_out_behavior),
            runtime_paths=[Path(path) for path in args.runtime],
            regression_runtime_paths=[Path(path) for path in args.regression_runtime],
        )
        write_evaluation_evidence_index(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Phase 5 evaluation evidence indexing failed: {exc}", file=sys.stderr)
        return 2

    print(f"Phase 5 evidence index: {Path(args.output).resolve()}")
    return 0


def build_inference_benchmark(args: argparse.Namespace) -> int:
    configure_import_path()

    from app.evaluation.inference_benchmark import (
        build_inference_benchmark_report,
        format_inference_benchmark_summary,
        load_benchmark_contract,
        load_generation_evidence,
        load_inference_measurement,
        write_inference_benchmark_report,
    )

    try:
        contract = load_benchmark_contract(Path(args.contract))
        measurement = load_inference_measurement(Path(args.measurement))
        quality_report_path = Path(args.quality_report)
        quality_report = load_generation_evidence(quality_report_path)
        report = build_inference_benchmark_report(
            contract,
            measurement,
            quality_report,
            quality_report_path=quality_report_path,
        )
        write_inference_benchmark_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Inference benchmark report failed: {exc}", file=sys.stderr)
        return 2

    print(format_inference_benchmark_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def profile_native_vector_candidate(args: argparse.Namespace) -> int:
    configure_import_path()

    from app.evaluation.native_profile import (
        build_native_profile_report,
        format_native_profile_summary,
        load_native_profile_contract,
        write_native_profile_report,
    )

    try:
        report = build_native_profile_report(load_native_profile_contract(Path(args.contract)))
        write_native_profile_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Native vector profile failed: {exc}", file=sys.stderr)
        return 2

    print(format_native_profile_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0


def verify_native_vector_candidate(args: argparse.Namespace) -> int:
    configure_import_path()

    from app.evaluation.native_verification import (
        build_native_verification_report,
        format_native_verification_summary,
        load_native_verification_contract,
        write_native_verification_report,
    )

    try:
        report = build_native_verification_report(
            load_native_verification_contract(Path(args.contract)),
            Path(args.library),
        )
        write_native_verification_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Native vector verification failed: {exc}", file=sys.stderr)
        return 2

    print(format_native_verification_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def evaluate_native_vector_ranking(args: argparse.Namespace) -> int:
    configure_import_path()

    from app.evaluation.native_ranking import (
        evaluate_contiguous_ranking,
        format_native_ranking_summary,
        load_native_ranking_contract,
        write_native_ranking_report,
    )

    try:
        report = evaluate_contiguous_ranking(
            load_native_ranking_contract(Path(args.contract)),
            Path(args.library),
        )
        write_native_ranking_report(report, Path(args.output))
    except (OSError, ValueError) as exc:
        print(f"Native vector ranking failed: {exc}", file=sys.stderr)
        return 2

    print(format_native_ranking_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def offline_bundle_build(args: argparse.Namespace) -> int:
    from delivery.offline_bundle import (
        BundleError,
        build_offline_bundle,
        format_verification_summary,
        verify_offline_bundle,
    )

    try:
        manifest = build_offline_bundle(Path(args.spec), Path(args.output))
        report = verify_offline_bundle(Path(args.output))
    except (BundleError, OSError, ValueError) as exc:
        print(f"Offline bundle build failed: {exc}", file=sys.stderr)
        return 2
    print(f"Offline bundle built: {Path(args.output).resolve()}")
    print(f"Release: {manifest.release_id}")
    print(format_verification_summary(report))
    return 0 if report.passed else 1


def release_source_verify(args: argparse.Namespace) -> int:
    sys.dont_write_bytecode = True
    from delivery.release_source import (
        ReleaseSourceError,
        build_release_source_report,
        format_release_source_summary,
        load_release_source_contract,
        write_release_source_report,
    )

    try:
        contract = load_release_source_contract(Path(args.contract))
        report = build_release_source_report(
            contract,
            source_root=Path(args.source),
            expected_revision=args.expected_revision,
        )
        write_release_source_report(report, Path(args.output))
    except (OSError, ReleaseSourceError, ValueError) as exc:
        print(f"Release source preflight failed: {exc}", file=sys.stderr)
        return 2

    print(format_release_source_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report.passed else 1


def release_trust_policy_verify(args: argparse.Namespace) -> int:
    from delivery.trust_policy import load_release_trust_policy

    try:
        policy = load_release_trust_policy(Path(args.policy))
    except (OSError, ValueError) as exc:
        print(f"Release trust policy validation failed: {exc}", file=sys.stderr)
        return 2

    print("Release trust policy: PASS")
    print(f"Policy: {policy.policy_id}")
    print(f"Zones: {len(policy.zones)}")
    print(f"Assets: {len(policy.assets)}")
    print(f"Failure rules: {len(policy.failure_rules)}")
    return 0


def offline_bundle_verify(args: argparse.Namespace) -> int:
    from delivery.offline_bundle import (
        format_verification_summary,
        verify_offline_bundle,
    )

    report = verify_offline_bundle(Path(args.bundle))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(format_verification_summary(report))
    return 0 if report.passed else 1


def retrieval_cleanup(_args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.db.session import SessionLocal
    from app.services.retrieval_runs import cleanup_expired_retrieval_runs

    with SessionLocal() as db:
        deleted = cleanup_expired_retrieval_runs(db)
    print(f"Deleted {deleted} expired retrieval runs")
    return 0


def training_preflight(args: argparse.Namespace) -> int:
    from training.foundation import (
        TrainingFoundationError,
        collect_preflight_report,
        format_preflight_summary,
        load_training_config,
        write_json_report,
    )

    try:
        config = load_training_config(Path(args.config))
        report = collect_preflight_report(config, cache_dir=Path(args.cache_dir).expanduser())
        write_json_report(report, Path(args.output))
    except (OSError, TrainingFoundationError) as exc:
        print(f"Training preflight failed: {exc}", file=sys.stderr)
        return 2

    print(format_preflight_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_calibrate(args: argparse.Namespace) -> int:
    from training.calibration import format_calibration_summary, run_calibration
    from training.foundation import TrainingFoundationError, load_training_config

    try:
        config = load_training_config(Path(args.config))
        report = run_calibration(
            config,
            output=Path(args.output),
            local_files_only=args.local_files_only,
        )
    except (OSError, TrainingFoundationError) as exc:
        print(f"Training calibration failed: {exc}", file=sys.stderr)
        return 2

    print(format_calibration_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_template_check(args: argparse.Namespace) -> int:
    from training.continuity import verify_chat_template
    from training.foundation import TrainingFoundationError, load_training_config

    try:
        config = load_training_config(Path(args.config))
        report = verify_chat_template(
            config,
            template_path=Path(args.template),
            output=Path(args.output),
            local_files_only=args.local_files_only,
        )
    except (OSError, TrainingFoundationError, ValueError) as exc:
        print(f"Training template check failed: {exc}", file=sys.stderr)
        return 2

    print(f"Training template check: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"System role strategy: {report['system_role_strategy']}")
    print(f"Template SHA-256: {report['template_sha256']}")
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_continuity(args: argparse.Namespace) -> int:
    from training.continuity import (
        build_continuity_report,
        format_continuity_summary,
        generate_runtime_answers,
        generate_source_answers,
        load_diagnostics,
    )
    from training.foundation import (
        TrainingFoundationError,
        load_training_config,
        write_json_report,
    )

    try:
        config = load_training_config(Path(args.config))
        diagnostics = load_diagnostics(Path(args.diagnostics))
        source_answers = generate_source_answers(
            config,
            diagnostics,
            template_path=Path(args.template),
            local_files_only=args.local_files_only,
        )
        runtime_answers = generate_runtime_answers(
            diagnostics,
            runtime_url=args.runtime_url,
        )
        report = build_continuity_report(
            config,
            diagnostics,
            source_answers=source_answers,
            runtime_answers=runtime_answers,
            runtime_url=args.runtime_url,
        )
        write_json_report(report, Path(args.output))
    except (OSError, TrainingFoundationError, ValueError) as exc:
        print(f"Training continuity failed: {exc}", file=sys.stderr)
        return 2

    print(format_continuity_summary(report))
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_data_validate(args: argparse.Namespace) -> int:
    from training.data_contract import build_validation_report
    from training.foundation import TrainingFoundationError, write_json_report

    try:
        report = build_validation_report(
            Path(args.manifest),
            config_path=Path(args.config),
            token_counter=getattr(args, "token_counter", None),
        )
        write_json_report(report, Path(args.output))
    except (OSError, TrainingFoundationError, ValueError) as exc:
        print(f"Training data validation failed: {exc}", file=sys.stderr)
        return 2

    print(f"Training data validation: {'PASS' if report['passed'] else 'FAIL'}")
    if report["passed"]:
        print(f"Dataset: {report['dataset_id']} {report['dataset_version']}")
        print(f"Examples: {report['example_count']}")
    else:
        print(f"Issues: {report['issue_count']}")
        for issue in report["issues"][:10]:
            print(f"- {issue['location']}: {issue['code']}: {issue['message']}")
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_run(args: argparse.Namespace) -> int:
    from training.foundation import TrainingFoundationError, load_training_config
    from training.trainer import TrainingRunError, run_bounded_training

    try:
        config = load_training_config(Path(args.config))
        report = run_bounded_training(
            config,
            manifest_path=Path(args.manifest),
            output_dir=Path(args.output_dir),
            rank=args.rank,
            learning_rate=args.learning_rate,
            resume_from=Path(args.resume_from) if args.resume_from else None,
            local_files_only=args.local_files_only,
            config_path=Path(args.config),
        )
    except (OSError, TrainingFoundationError, TrainingRunError, ValueError) as exc:
        print(f"Bounded LoRA training failed: {exc}", file=sys.stderr)
        return 2

    print("Bounded LoRA training: PASS")
    print(f"Adapter: {report['adapter_id']}")
    print(f"Steps: {report['completed_steps']}")
    print(f"Report: {(Path(args.output_dir) / 'training-report.json').resolve()}")
    return 0


def training_evaluate_candidate(args: argparse.Namespace) -> int:
    from training.candidate_evaluation import run_candidate_evaluation
    from training.foundation import TrainingFoundationError, load_training_config
    from training.trainer import TrainingRunError

    try:
        config = load_training_config(Path(args.config))
        report = run_candidate_evaluation(
            config,
            manifest_path=Path(args.manifest),
            training_manifest_path=(
                Path(args.training_manifest) if args.training_manifest else None
            ),
            adapter_path=Path(args.adapter),
            training_report_path=Path(args.training_report),
            output=Path(args.output),
            local_files_only=args.local_files_only,
            max_new_tokens=args.max_new_tokens,
            config_path=Path(args.config),
        )
    except (OSError, TrainingFoundationError, TrainingRunError, ValueError) as exc:
        print(f"Held-out candidate evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Held-out candidate evaluation: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"Adapter: {report['adapter_id']}")
    print(f"Behavior score: {report['metrics']['behavior_score']:.3f}")
    print(f"Report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def training_select_candidate(args: argparse.Namespace) -> int:
    from training.candidate_evaluation import build_candidate_selection_report
    from training.trainer import TrainingRunError

    try:
        report = build_candidate_selection_report(
            [Path(path) for path in args.training_report],
            [Path(path) for path in args.held_out_report],
            output=Path(args.output),
        )
    except (OSError, TrainingRunError, ValueError) as exc:
        print(f"Candidate selection failed: {exc}", file=sys.stderr)
        return 2
    print("Bounded candidate selection: PASS")
    print(f"Selected adapter: {report['selected_adapter_id']}")
    print(f"Development eligible: {report['held_out_selection_eligible']}")
    print(f"Promotion eligible: {report['promotion_eligible']}")
    print(f"Report: {Path(args.output).resolve()}")
    return 0


def training_export_adapter(args: argparse.Namespace) -> int:
    from training.adapter_export import export_adapter_to_gguf
    from training.foundation import TrainingFoundationError, load_training_config
    from training.trainer import TrainingRunError

    try:
        config = load_training_config(Path(args.config))
        report = export_adapter_to_gguf(
            config,
            adapter_path=Path(args.adapter),
            training_report_path=Path(args.training_report),
            selection_report_path=Path(args.selection_report),
            output_dir=Path(args.output_dir),
            llama_cpp_dir=Path(args.llama_cpp_dir).expanduser(),
            base_model_dir=Path(args.base_model_dir).expanduser(),
        )
    except (OSError, TrainingFoundationError, TrainingRunError, ValueError) as exc:
        print(f"Adapter export failed: {exc}", file=sys.stderr)
        return 2
    print("Adapter export: PASS")
    print(f"Adapter: {report['adapter_id']}")
    print(f"GGUF: {report['runtime']['gguf_file']}")
    print(f"Manifest: {(Path(args.output_dir) / 'manifest.json').resolve()}")
    return 0


def training_evaluate_runtime_adapter(args: argparse.Namespace) -> int:
    from training.candidate_evaluation import run_deployed_candidate_evaluation
    from training.foundation import TrainingFoundationError, load_training_config
    from training.trainer import TrainingRunError

    try:
        report = run_deployed_candidate_evaluation(
            load_training_config(Path(args.config)),
            manifest_path=Path(args.manifest),
            training_framework_report_path=Path(args.training_framework_report),
            output=Path(args.output),
            runtime_base_url=args.runtime_url,
            runtime_model=args.runtime_model,
            adapter_id=args.adapter_id,
            adapter_sha256=args.adapter_sha256,
            max_new_tokens=args.max_new_tokens,
            config_path=Path(args.config),
        )
    except (OSError, TrainingFoundationError, TrainingRunError, ValueError) as exc:
        print(f"Deployed adapter evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Deployed adapter evaluation: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"Cases: {report['case_count']}")
    print(f"Metrics: {report['metrics']}")
    print(f"JSON report: {Path(args.output).resolve()}")
    return 0 if report["passed"] else 1


def ingestion_worker(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from redis.exceptions import RedisError

    from app.cache.redis import get_redis_client
    from app.config import get_settings
    from app.services.document_ingestion_queue import process_next_ingestion_job
    from app.services.document_ingestion_queue import recover_reserved_ingestion_jobs

    settings = get_settings()
    redis_client = get_redis_client()

    try:
        recovered = recover_reserved_ingestion_jobs(
            redis_client,
            queue_name=settings.document_ingestion_queue_name,
        )
        if recovered:
            print(f"Recovered {recovered} interrupted document ingestion jobs")
        while True:
            processed = process_next_ingestion_job(redis_client, settings=settings)
            if args.once:
                if processed:
                    print("Processed one document ingestion job")
                    return 0
                print("No document ingestion job available")
                return 0
    except RedisError as exc:
        print(f"Document ingestion worker failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./manage.py",
        description="Offline Intelligence Hub development commands",
    )
    parser.add_argument(
        "--env-file",
        help="override the command's profile environment file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    runserver_parser = subparsers.add_parser("runserver", help="start the API server")
    runserver_parser.set_defaults(func=runserver)

    migrate_parser = subparsers.add_parser("migrate", help="apply database migrations")
    migrate_parser.set_defaults(func=migrate)

    test_parser = subparsers.add_parser("test", help="run the test suite")
    test_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    test_parser.set_defaults(func=test)

    test_container_parser = subparsers.add_parser(
        "test-container",
        help="run the test suite inside Docker Compose",
    )
    test_container_parser.set_defaults(func=test_container)

    e2e_setup_parser = subparsers.add_parser(
        "e2e-setup",
        help="create and migrate the isolated browser-test environment",
    )
    e2e_setup_parser.set_defaults(func=e2e_setup)

    e2e_cleanup_parser = subparsers.add_parser(
        "e2e-cleanup",
        help="clear data and files from the isolated browser-test environment",
    )
    e2e_cleanup_parser.set_defaults(func=e2e_cleanup)

    lint_parser = subparsers.add_parser("lint", help="run ruff")
    lint_parser.set_defaults(func=lint)

    typecheck_parser = subparsers.add_parser("typecheck", help="run mypy")
    typecheck_parser.set_defaults(func=typecheck)

    smoke_parser = subparsers.add_parser("smoke", help="run the HTTP smoke test")
    smoke_parser.set_defaults(func=smoke)

    llm_probe_parser = subparsers.add_parser(
        "llm-probe",
        help="send a prompt to the configured LLM backend",
    )
    llm_probe_parser.add_argument(
        "prompt",
        nargs="?",
        default="Say hello from the local LLM probe.",
    )
    llm_probe_parser.add_argument("--max-tokens", type=int, default=128)
    llm_probe_parser.add_argument("--temperature", type=float, default=0.2)
    llm_probe_parser.set_defaults(func=llm_probe)

    llm_start_parser = subparsers.add_parser(
        "llm-start",
        help="start the configured llama.cpp server",
    )
    llm_start_parser.add_argument(
        "--profile",
        help="load config/models/<profile>.env or a profile file path",
    )
    llm_start_parser.set_defaults(func=llm_start)

    llm_check_parser = subparsers.add_parser(
        "llm-check",
        help="check the configured llama.cpp server",
    )
    llm_check_parser.set_defaults(func=llm_check)

    llm_stop_parser = subparsers.add_parser(
        "llm-stop",
        help="gracefully stop the configured llama.cpp server",
    )
    llm_stop_parser.set_defaults(func=llm_stop)

    embedding_start_parser = subparsers.add_parser(
        "embedding-start",
        help="start the dedicated llama.cpp embedding server",
    )
    embedding_start_parser.set_defaults(func=embedding_start)

    embedding_check_parser = subparsers.add_parser(
        "embedding-check",
        help="check the dedicated embedding server",
    )
    embedding_check_parser.set_defaults(func=embedding_check)

    embedding_stop_parser = subparsers.add_parser(
        "embedding-stop",
        help="gracefully stop the dedicated embedding server",
    )
    embedding_stop_parser.set_defaults(func=embedding_stop)

    reranker_start_parser = subparsers.add_parser(
        "reranker-start", help="start the dedicated llama.cpp reranker server"
    )
    reranker_start_parser.set_defaults(func=reranker_start)
    reranker_check_parser = subparsers.add_parser(
        "reranker-check", help="check the dedicated reranker server"
    )
    reranker_check_parser.set_defaults(func=reranker_check)
    reranker_stop_parser = subparsers.add_parser(
        "reranker-stop", help="gracefully stop the dedicated reranker server"
    )
    reranker_stop_parser.set_defaults(func=reranker_stop)

    embedding_reindex_parser = subparsers.add_parser(
        "embedding-reindex",
        help="replace stored document chunk embeddings using the configured provider",
    )
    embedding_reindex_parser.add_argument(
        "--stale-only",
        action="store_true",
        help="only re-embed chunks missing vectors or using another embedding model",
    )
    embedding_reindex_parser.set_defaults(func=embedding_reindex)

    evaluation_parser = subparsers.add_parser(
        "evaluate-retrieval",
        help="seed a versioned corpus and evaluate a retrieval strategy",
    )
    evaluation_parser.add_argument(
        "--dataset",
        default="evaluation/datasets/dense-baseline-smoke-v1.jsonl",
    )
    evaluation_parser.add_argument(
        "--output",
        default="var/evaluation/dense-baseline-latest.json",
    )
    evaluation_parser.add_argument("--limit", type=int, default=5, choices=range(1, 21))
    evaluation_parser.add_argument(
        "--strategy",
        choices=("dense", "lexical", "hybrid", "reranked", "multi_query"),
        default="dense",
    )
    evaluation_parser.add_argument("--min-recall", type=float)
    evaluation_parser.add_argument("--min-precision", type=float)
    evaluation_parser.add_argument("--min-mrr", type=float)
    evaluation_parser.add_argument("--min-hit-rate", type=float)
    evaluation_parser.add_argument("--min-no-result-accuracy", type=float)
    evaluation_parser.add_argument("--max-mean-latency-ms", type=float)
    evaluation_parser.add_argument("--max-p95-latency-ms", type=float)
    evaluation_parser.add_argument("--max-authorization-leaks", type=int, default=0)
    evaluation_parser.add_argument("--allow-model-mismatch", action="store_true")
    evaluation_parser.set_defaults(func=evaluate_retrieval)

    generation_parser = subparsers.add_parser(
        "evaluate-generation",
        help="evaluate grounded RAG answer quality and streaming performance",
    )
    generation_parser.add_argument(
        "--dataset",
        default="evaluation/datasets/dense-baseline-v1.jsonl",
    )
    generation_parser.add_argument(
        "--output",
        default="var/evaluation/generation-baseline-latest.json",
    )
    generation_parser.add_argument("--limit", type=int, default=5, choices=range(1, 21))
    generation_parser.add_argument(
        "--mode",
        choices=("base", "base_rag", "adapter", "adapter_rag"),
        default="base_rag",
        help="select base/adapter runtime with or without dense RAG",
    )
    generation_parser.add_argument("--min-parse-success", type=float)
    generation_parser.add_argument("--min-fact-coverage", type=float)
    generation_parser.add_argument("--min-citation-accuracy", type=float)
    generation_parser.add_argument("--min-citation-coverage", type=float)
    generation_parser.add_argument("--min-faithfulness", type=float)
    generation_parser.add_argument("--max-hallucination", type=float)
    generation_parser.add_argument("--min-refusal-accuracy", type=float)
    generation_parser.add_argument("--max-restricted-fact-leaks", type=int, default=0)
    generation_parser.add_argument("--max-mean-ttft-ms", type=float)
    generation_parser.add_argument("--max-p95-ttft-ms", type=float)
    generation_parser.add_argument("--max-mean-latency-ms", type=float)
    generation_parser.add_argument("--max-p95-latency-ms", type=float)
    generation_parser.add_argument("--min-tokens-per-second", type=float)
    generation_parser.add_argument("--allow-model-mismatch", action="store_true")
    generation_parser.set_defaults(func=evaluate_generation)

    evaluation_matrix_parser = subparsers.add_parser(
        "training-evaluation-matrix",
        help="assemble and gate the four-mode Phase 5 behavior evaluation matrix",
    )
    evaluation_matrix_parser.add_argument("--base", required=True)
    evaluation_matrix_parser.add_argument("--base-rag", required=True)
    evaluation_matrix_parser.add_argument("--adapter", required=True)
    evaluation_matrix_parser.add_argument("--adapter-rag", required=True)
    evaluation_matrix_parser.add_argument("--base-rag-regression", required=True)
    evaluation_matrix_parser.add_argument("--adapter-rag-regression", required=True)
    evaluation_matrix_parser.add_argument(
        "--output",
        default="var/training/evaluation-matrix-latest.json",
    )
    evaluation_matrix_parser.add_argument("--min-language-adherence", type=float, default=1.0)
    evaluation_matrix_parser.add_argument("--min-citation-format-validity", type=float, default=1.0)
    evaluation_matrix_parser.add_argument("--min-json-schema-validity", type=float, default=1.0)
    evaluation_matrix_parser.add_argument("--min-incident-report-structure", type=float, default=1.0)
    evaluation_matrix_parser.add_argument("--min-terminology-consistency", type=float, default=1.0)
    evaluation_matrix_parser.add_argument("--min-supported-refusal", type=float, default=1.0)
    evaluation_matrix_parser.add_argument(
        "--gate-mode",
        action="append",
        choices=("base", "base_rag", "adapter", "adapter_rag"),
        help="mode to gate with task thresholds; repeat as needed (default: adapter_rag)",
    )
    evaluation_matrix_parser.set_defaults(func=build_training_evaluation_matrix)

    evaluation_index_parser = subparsers.add_parser(
        "training-evaluation-index",
        help="cross-reference the separated Phase 5 validation, training, held-out, and runtime reports",
    )
    evaluation_index_parser.add_argument("--dataset-validation", required=True)
    evaluation_index_parser.add_argument("--training-run", required=True)
    evaluation_index_parser.add_argument("--held-out-behavior", required=True)
    evaluation_index_parser.add_argument(
        "--runtime",
        action="append",
        required=True,
        help="production runtime report; provide all four modes",
    )
    evaluation_index_parser.add_argument(
        "--regression-runtime",
        action="append",
        required=True,
        help="protected Phase 4 runtime report; provide base_rag and adapter_rag",
    )
    evaluation_index_parser.add_argument(
        "--output",
        default="var/training/phase-5-evidence-index.json",
    )
    evaluation_index_parser.set_defaults(func=build_training_evaluation_index)

    inference_benchmark_parser = subparsers.add_parser(
        "inference-benchmark-report",
        help="validate Phase 6 runtime measurements and protected quality evidence",
    )
    inference_benchmark_parser.add_argument(
        "--contract",
        default="config/models/gemma3-1b-q4-benchmark-v1.json",
    )
    inference_benchmark_parser.add_argument("--measurement", required=True)
    inference_benchmark_parser.add_argument("--quality-report", required=True)
    inference_benchmark_parser.add_argument(
        "--output",
        default="var/inference/gemma3-1b-q4-benchmark-latest.json",
    )
    inference_benchmark_parser.set_defaults(func=build_inference_benchmark)

    native_profile_parser = subparsers.add_parser(
        "native-vector-profile",
        help="record the Phase 8 Python batch-cosine baseline",
    )
    native_profile_parser.add_argument(
        "--contract",
        default="config/native/vector-similarity-profile-v1.json",
    )
    native_profile_parser.add_argument(
        "--output",
        default="var/native/vector-similarity-python-baseline.json",
    )
    native_profile_parser.set_defaults(func=profile_native_vector_candidate)

    native_verification_parser = subparsers.add_parser(
        "native-vector-verify",
        help="verify Phase 8 native numerical correctness and boundary performance",
    )
    native_verification_parser.add_argument(
        "--contract",
        default="config/native/vector-similarity-verification-v1.json",
    )
    native_verification_parser.add_argument("--library", required=True)
    native_verification_parser.add_argument(
        "--output",
        default="var/native/vector-similarity-verification.json",
    )
    native_verification_parser.set_defaults(func=verify_native_vector_candidate)

    native_ranking_parser = subparsers.add_parser(
        "native-vector-ranking-evaluate",
        help="evaluate top-k ranking over an already-contiguous float32 matrix",
    )
    native_ranking_parser.add_argument(
        "--contract",
        default="config/native/vector-ranking-evaluation-v1.json",
    )
    native_ranking_parser.add_argument("--library", required=True)
    native_ranking_parser.add_argument(
        "--output",
        default="var/native/vector-ranking-evaluation.json",
    )
    native_ranking_parser.set_defaults(func=evaluate_native_vector_ranking)

    release_source_parser = subparsers.add_parser(
        "release-source-verify",
        help="fail closed unless a release source tree and Docker context are clean",
    )
    release_source_parser.add_argument(
        "--contract",
        default="config/supply-chain/release-source-v1.json",
    )
    release_source_parser.add_argument("--source", default=".")
    release_source_parser.add_argument("--expected-revision", required=True)
    release_source_parser.add_argument(
        "--output",
        default="var/release/source-preflight-latest.json",
    )
    release_source_parser.set_defaults(func=release_source_verify)

    release_trust_parser = subparsers.add_parser(
        "release-trust-policy-verify",
        help="validate the Phase 9 offline release trust policy",
    )
    release_trust_parser.add_argument(
        "--policy",
        default="config/supply-chain/release-trust-policy-v1.json",
    )
    release_trust_parser.set_defaults(func=release_trust_policy_verify)

    offline_bundle_build_parser = subparsers.add_parser(
        "offline-bundle-build",
        help="build and verify a deterministic Phase 7 offline release directory",
    )
    offline_bundle_build_parser.add_argument("--spec", required=True)
    offline_bundle_build_parser.add_argument("--output", required=True)
    offline_bundle_build_parser.set_defaults(func=offline_bundle_build)

    offline_bundle_verify_parser = subparsers.add_parser(
        "offline-bundle-verify",
        help="verify exact paths, sizes, and checksums in an offline release directory",
    )
    offline_bundle_verify_parser.add_argument("--bundle", required=True)
    offline_bundle_verify_parser.add_argument("--output")
    offline_bundle_verify_parser.set_defaults(func=offline_bundle_verify)

    training_preflight_parser = subparsers.add_parser(
        "training-preflight",
        help="verify the pinned Phase 5 environment, hardware, disk, and model access",
    )
    training_preflight_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_preflight_parser.add_argument(
        "--cache-dir",
        default="var/training/cache",
    )
    training_preflight_parser.add_argument(
        "--output",
        default="var/training/preflight-latest.json",
    )
    training_preflight_parser.set_defaults(func=training_preflight)

    training_calibrate_parser = subparsers.add_parser(
        "training-calibrate",
        help="run one BF16/FP16 LoRA forward-backward step at each planned sequence length",
    )
    training_calibrate_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_calibrate_parser.add_argument(
        "--output",
        default="var/training/calibration-latest.json",
    )
    training_calibrate_parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="refuse network access and load the pinned model only from the local Hugging Face cache",
    )
    training_calibrate_parser.set_defaults(func=training_calibrate)

    training_template_parser = subparsers.add_parser(
        "training-template-check",
        help="verify the pinned Gemma template and production system-role mapping",
    )
    training_template_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_template_parser.add_argument(
        "--template",
        default="config/training/gemma3-chat-template.jinja",
    )
    training_template_parser.add_argument(
        "--output",
        default="var/training/template-check-latest.json",
    )
    training_template_parser.add_argument("--local-files-only", action="store_true")
    training_template_parser.set_defaults(func=training_template_check)

    training_continuity_parser = subparsers.add_parser(
        "training-continuity",
        help="compare pinned source-model and GGUF-runtime behavior on deterministic cases",
    )
    training_continuity_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_continuity_parser.add_argument(
        "--template",
        default="config/training/gemma3-chat-template.jinja",
    )
    training_continuity_parser.add_argument(
        "--diagnostics",
        default="config/training/continuity-diagnostics-v1.json",
    )
    training_continuity_parser.add_argument(
        "--runtime-url",
        default="http://127.0.0.1:18080/v1",
    )
    training_continuity_parser.add_argument(
        "--output",
        default="var/training/continuity-latest.json",
    )
    training_continuity_parser.add_argument("--local-files-only", action="store_true")
    training_continuity_parser.set_defaults(func=training_continuity)

    training_data_parser = subparsers.add_parser(
        "training-data-validate",
        help="validate a Phase 5 training manifest and its JSONL examples",
    )
    training_data_parser.add_argument("--manifest", required=True)
    training_data_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_data_parser.add_argument(
        "--output",
        default="var/training/data-validation-latest.json",
    )
    training_data_parser.set_defaults(func=training_data_validate)

    training_run_parser = subparsers.add_parser(
        "training-run",
        help="run one bounded, manifest-validated LoRA training candidate on CUDA",
    )
    training_run_parser.add_argument("--manifest", required=True)
    training_run_parser.add_argument("--output-dir", required=True)
    training_run_parser.add_argument(
        "--config",
        default="config/training/gemma3-1b-lora-v1.json",
    )
    training_run_parser.add_argument("--rank", type=int, choices=(8, 16))
    training_run_parser.add_argument("--learning-rate", type=float)
    training_run_parser.add_argument("--resume-from")
    training_run_parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="refuse downloads and load the pinned model/tokenizer from the local cache",
    )
    training_run_parser.set_defaults(func=training_run)

    candidate_evaluation_parser = subparsers.add_parser(
        "training-evaluate-candidate",
        help="evaluate a PEFT adapter on an untouched held-out or independent development set",
    )
    candidate_evaluation_parser.add_argument("--manifest", required=True)
    candidate_evaluation_parser.add_argument(
        "--training-manifest",
        help="training corpus manifest when --manifest is a separate development corpus",
    )
    candidate_evaluation_parser.add_argument("--adapter", required=True)
    candidate_evaluation_parser.add_argument("--training-report", required=True)
    candidate_evaluation_parser.add_argument(
        "--output", default="var/training/held-out-candidate-latest.json"
    )
    candidate_evaluation_parser.add_argument(
        "--config", default="config/training/gemma3-1b-lora-v1.json"
    )
    candidate_evaluation_parser.add_argument("--max-new-tokens", type=int, default=192)
    candidate_evaluation_parser.add_argument("--local-files-only", action="store_true")
    candidate_evaluation_parser.set_defaults(func=training_evaluate_candidate)

    candidate_selection_parser = subparsers.add_parser(
        "training-select-candidate",
        help="select from paired bounded training and development reports",
    )
    candidate_selection_parser.add_argument(
        "--training-report",
        action="append",
        required=True,
        help="repeat once per candidate in the same order as --held-out-report",
    )
    candidate_selection_parser.add_argument(
        "--held-out-report",
        action="append",
        required=True,
        help="repeat once per candidate in the same order as --training-report",
    )
    candidate_selection_parser.add_argument(
        "--output",
        default="var/training/bounded-candidate-selection-latest.json",
    )
    candidate_selection_parser.set_defaults(func=training_select_candidate)

    adapter_export_parser = subparsers.add_parser(
        "training-export-adapter",
        help="validate and immutably export a selected PEFT adapter to GGUF",
    )
    adapter_export_parser.add_argument("--adapter", required=True)
    adapter_export_parser.add_argument("--training-report", required=True)
    adapter_export_parser.add_argument("--selection-report", required=True)
    adapter_export_parser.add_argument("--output-dir", required=True)
    adapter_export_parser.add_argument(
        "--config", default="config/training/gemma3-1b-lora-v2.json"
    )
    adapter_export_parser.add_argument(
        "--llama-cpp-dir", default="/home/imroot/tools/llama.cpp"
    )
    adapter_export_parser.add_argument("--base-model-dir", required=True)
    adapter_export_parser.set_defaults(func=training_export_adapter)

    runtime_adapter_parser = subparsers.add_parser(
        "training-evaluate-runtime-adapter",
        help="compare a deployed GGUF adapter with its training-framework held-out results",
    )
    runtime_adapter_parser.add_argument(
        "--config", default="config/training/gemma3-1b-lora-v2.json"
    )
    runtime_adapter_parser.add_argument("--manifest", required=True)
    runtime_adapter_parser.add_argument("--training-framework-report", required=True)
    runtime_adapter_parser.add_argument("--output", required=True)
    runtime_adapter_parser.add_argument("--runtime-url", default="http://127.0.0.1:8080/v1")
    runtime_adapter_parser.add_argument("--runtime-model", required=True)
    runtime_adapter_parser.add_argument("--adapter-id", required=True)
    runtime_adapter_parser.add_argument("--adapter-sha256", required=True)
    runtime_adapter_parser.add_argument("--max-new-tokens", type=int, default=192)
    runtime_adapter_parser.set_defaults(func=training_evaluate_runtime_adapter)

    retrieval_cleanup_parser = subparsers.add_parser(
        "retrieval-cleanup",
        help="delete retrieval diagnostics past their configured expiry",
    )
    retrieval_cleanup_parser.set_defaults(func=retrieval_cleanup)

    ingestion_worker_parser = subparsers.add_parser(
        "ingestion-worker",
        help="process queued document ingestion jobs from Redis",
    )
    ingestion_worker_parser.add_argument("--once", action="store_true", help="process at most one queued job")
    ingestion_worker_parser.set_defaults(func=ingestion_worker)

    return parser


def main() -> int:
    configure_import_path()
    parser = build_parser()
    args = parser.parse_args()
    if args.env_file:
        os.environ["APP_ENV_FILE"] = args.env_file
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
