from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.evaluation.generation import (  # noqa: E402
    answer_uses_language,
    citation_format_is_valid,
    incident_report_has_sections,
    json_answer_matches_schema,
    terminology_is_consistent,
)
from app.retrieval.context import build_grounded_system_message  # noqa: E402


REVIEWED_AT = "2026-07-17T18:00:00+03:00"
TASKS = (
    "grounded_answer",
    "grounded_refusal",
    "citation_formatting",
    "json_output",
    "incident_report",
    "terminology",
)


@dataclass(frozen=True)
class Scenario:
    slug: str
    name_en: str
    name_tr: str
    filename_en: str
    filename_tr: str
    status_en: str
    status_tr: str
    interval_minutes: int
    window: str
    owner_en: str
    owner_tr: str
    term_en: str
    term_tr: str
    deprecated_en: str
    deprecated_tr: str
    incident_start: str
    incident_end: str
    cause_en: str
    cause_tr: str
    action_en: str
    action_tr: str


def json_schema(language: str) -> dict[str, Any]:
    if language == "en":
        return {
            "type": "object",
            "required": ["status", "interval_minutes", "source"],
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["ready"]},
                "interval_minutes": {"type": "integer"},
                "source": {"type": "string"},
            },
        }
    return {
        "type": "object",
        "required": ["durum", "aralik_dakika", "kaynak"],
        "additionalProperties": False,
        "properties": {
            "durum": {"type": "string", "enum": ["hazır"]},
            "aralik_dakika": {"type": "integer"},
            "kaynak": {"type": "string"},
        },
    }


def _source_text(scenario: Scenario, language: str) -> str:
    if language == "en":
        return (
            f"The fictional {scenario.name_en} service is {scenario.status_en}. Its polling interval "
            f"is {scenario.interval_minutes} minutes and its operating window starts at "
            f"{scenario.window}. The {scenario.owner_en} owns it. The approved term is "
            f"{scenario.term_en}; {scenario.deprecated_en} is deprecated. During a test incident, "
            f"the service was unavailable from {scenario.incident_start} to {scenario.incident_end} "
            f"because {scenario.cause_en}. {scenario.action_en}."
        )
    return (
        f"Kurgusal {scenario.name_tr} hizmeti {scenario.status_tr}. Yoklama aralığı "
        f"{scenario.interval_minutes} dakikadır ve çalışma aralığı {scenario.window} saatinde başlar. "
        f"Hizmetin sorumlusu {scenario.owner_tr}. Onaylı terim {scenario.term_tr}; "
        f"{scenario.deprecated_tr} ifadesi kullanımdan kaldırılmıştır. Test olayında hizmet "
        f"{scenario.incident_start} ile {scenario.incident_end} arasında {scenario.cause_tr} nedeniyle "
        f"kullanılamadı. {scenario.action_tr}."
    )


def _distractor_text(index: int, language: str) -> str:
    if language == "en":
        return (
            f"The unrelated Quartz archive retains synthetic audit bundles for {20 + index} days. "
            "It does not describe the requested service."
        )
    return (
        f"İlgisiz Kuvars arşivi sentetik denetim paketlerini {20 + index} gün saklar. "
        "İstenen hizmeti açıklamaz."
    )


def _render_context(
    scenario: Scenario,
    language: str,
    index: int,
    *,
    include_relevant: bool,
) -> tuple[str, int]:
    if not include_relevant and index % 2 == 0:
        return "", 0
    filename = scenario.filename_en if language == "en" else scenario.filename_tr
    relevant = _source_text(scenario, language)
    distractor = _distractor_text(index, language)
    if not include_relevant:
        return f"[Source 1: unrelated-{language}-{index:03d}.txt, chunk 0]\n{distractor}", 0
    if index % 3 == 0:
        return (
            f"[Source 1: unrelated-{language}-{index:03d}.txt, chunk 0]\n{distractor}\n\n"
            f"[Source 2: {filename}, chunk 0]\n{relevant}",
            2,
        )
    return (
        f"[Source 1: {filename}, chunk 0]\n{relevant}\n\n"
        f"[Source 2: unrelated-{language}-{index:03d}.txt, chunk 0]\n{distractor}",
        1,
    )


def _task_contract(
    task: str,
    language: str,
    scenario: Scenario,
    citation: str,
) -> tuple[str, str, dict[str, Any] | None, tuple[str, ...], tuple[str, ...]]:
    if language == "en":
        if task == "grounded_answer":
            return (
                f"When does the fictional {scenario.name_en} operating window begin, and who owns the service?",
                f"The operating window begins at {scenario.window}, and the {scenario.owner_en} owns the service. {citation}",
                None,
                (),
                (),
            )
        if task == "grounded_refusal":
            return (
                f"What is the emergency telephone extension for fictional {scenario.name_en}?",
                "The available documents do not provide the answer.",
                None,
                (),
                (),
            )
        if task == "citation_formatting":
            return (
                f"State the polling interval for fictional {scenario.name_en} and cite it using exact [Source N] format.",
                f"The polling interval is {scenario.interval_minutes} minutes. {citation}",
                None,
                (),
                (),
            )
        if task == "json_output":
            schema = json_schema(language)
            return (
                f"Return only a JSON object with status, interval_minutes, and source for fictional {scenario.name_en}. Put the exact citation label in source.",
                json.dumps(
                    {
                        "status": "ready",
                        "interval_minutes": scenario.interval_minutes,
                        "source": citation,
                    },
                    separators=(",", ":"),
                ),
                schema,
                (),
                (),
            )
        if task == "incident_report":
            sections = ("Impact", "Timeline", "Cause", "Action")
            return (
                f"Write a concise incident report for fictional {scenario.name_en} with headings Impact, Timeline, Cause, and Action. Cite factual statements.",
                (
                    f"Impact: The service was unavailable. {citation}\n"
                    f"Timeline: {scenario.incident_start} to {scenario.incident_end}. {citation}\n"
                    f"Cause: {scenario.cause_en}. {citation}\n"
                    f"Action: {scenario.action_en}. {citation}"
                ),
                None,
                sections,
                (),
            )
        return (
            f"Describe the saved restart position for fictional {scenario.name_en} using only the approved terminology and cite the source.",
            f"The saved restart position is the {scenario.term_en}. {citation}",
            None,
            (),
            (scenario.term_en, scenario.deprecated_en),
        )

    if task == "grounded_answer":
        return (
            f"Kurgusal {scenario.name_tr} çalışma aralığı ne zaman başlar ve hizmetten kim sorumludur?",
            f"Çalışma aralığı {scenario.window} saatinde başlar ve hizmetten {scenario.owner_tr} sorumludur. {citation}",
            None,
            (),
            (),
        )
    if task == "grounded_refusal":
        return (
            f"Kurgusal {scenario.name_tr} için acil telefon dahili numarası nedir?",
            "Mevcut belgeler bu sorunun yanıtını sağlamıyor.",
            None,
            (),
            (),
        )
    if task == "citation_formatting":
        return (
            f"Kurgusal {scenario.name_tr} yoklama aralığını belirtin ve tam [Source N] biçiminde kaynak gösterin.",
            f"Yoklama aralığı {scenario.interval_minutes} dakikadır. {citation}",
            None,
            (),
            (),
        )
    if task == "json_output":
        schema = json_schema(language)
        return (
            f"Kurgusal {scenario.name_tr} için yalnızca durum, aralik_dakika ve kaynak alanlarını içeren JSON nesnesi döndürün. Tam atıf etiketini kaynak alanına yazın.",
            json.dumps(
                {
                    "durum": "hazır",
                    "aralik_dakika": scenario.interval_minutes,
                    "kaynak": citation,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            schema,
            (),
            (),
        )
    if task == "incident_report":
        sections = ("Etki", "Zaman Çizelgesi", "Neden", "Eylem")
        return (
            f"Kurgusal {scenario.name_tr} olayı için Etki, Zaman Çizelgesi, Neden ve Eylem başlıklarıyla kısa rapor yazın. Olgusal ifadeleri kaynaklandırın.",
            (
                f"Etki: Hizmet kullanılamadı. {citation}\n"
                f"Zaman Çizelgesi: {scenario.incident_start} ile {scenario.incident_end} arası. {citation}\n"
                f"Neden: {scenario.cause_tr}. {citation}\n"
                f"Eylem: {scenario.action_tr}. {citation}"
            ),
            None,
            sections,
            (),
        )
    return (
        f"Kurgusal {scenario.name_tr} için kaydedilen yeniden başlatma konumunu yalnızca onaylı terimle açıklayın ve kaynak gösterin.",
        f"Kaydedilen yeniden başlatma konumu {scenario.term_tr} terimidir. {citation}",
        None,
        (),
        (scenario.term_tr, scenario.deprecated_tr),
    )


def _evaluation_user_prompt(task: str, language: str, scenario: Scenario) -> str:
    """Use a held-back instruction layout for validation/development examples."""
    if language == "en":
        prompts = {
            "grounded_answer": f"Using the evidence, identify fictional {scenario.name_en}'s window start and responsible team.",
            "grounded_refusal": f"Find the emergency phone extension for fictional {scenario.name_en}; do not guess if the evidence omits it.",
            "citation_formatting": f"According to the evidence, what polling interval applies to fictional {scenario.name_en}? Finish with its exact source label.",
            "json_output": f"For fictional {scenario.name_en}, emit an unfenced JSON object and nothing else. Required keys: status, interval_minutes, source.",
            "incident_report": f"Summarize fictional {scenario.name_en}'s event under exactly these labels: Impact, Timeline, Cause, Action. Ground the claims with source labels.",
            "terminology": f"Name fictional {scenario.name_en}'s persisted restart location with the evidence-approved term only, and cite it.",
        }
    else:
        prompts = {
            "grounded_answer": f"Kanıta göre kurgusal {scenario.name_tr} çalışma başlangıcını ve sorumlu ekibi belirleyin.",
            "grounded_refusal": f"Kurgusal {scenario.name_tr} acil telefon dahili numarasını bulun; kanıtta yoksa tahmin etmeyin.",
            "citation_formatting": f"Kanıta göre kurgusal {scenario.name_tr} yoklama aralığı nedir? Yanıtı tam kaynak etiketiyle bitirin.",
            "json_output": f"Kurgusal {scenario.name_tr} için yalnızca çitsiz bir JSON nesnesi üretin. Zorunlu anahtarlar: durum, aralik_dakika, kaynak.",
            "incident_report": f"Kurgusal {scenario.name_tr} olayını tam olarak Etki, Zaman Çizelgesi, Neden ve Eylem başlıkları altında, kaynak etiketleriyle özetleyin.",
            "terminology": f"Kurgusal {scenario.name_tr} kalıcı yeniden başlatma konumunu yalnızca kanıtta onaylanan terimle adlandırın ve kaynak gösterin.",
        }
    return prompts[task]


def build_example(
    *,
    task: str,
    language: str,
    index: int,
    scenario: Scenario,
    intended_split: Literal["train", "validation", "held_out"],
    dataset_slug: str,
    generator: str,
) -> dict[str, Any]:
    include_relevant = task != "grounded_refusal"
    context, source_number = _render_context(
        scenario,
        language,
        index,
        include_relevant=include_relevant,
    )
    citation = f"[Source {source_number}]" if source_number else ""
    user, assistant, target_schema, incident_sections, terms = _task_contract(
        task,
        language,
        scenario,
        citation,
    )
    contract_partition = "fit" if intended_split == "train" else intended_split
    if intended_split != "train":
        user = _evaluation_user_prompt(task, language, scenario)
    source_id = f"v3-{dataset_slug}-{scenario.slug}-{language}"
    distractor_id = f"v3-{dataset_slug}-unrelated-{language}-{index:03d}"
    provenance = [
        {
            "source_id": source_id,
            "source_uri": f"synthetic://phase5/{dataset_slug}/{source_id}",
            "license": "CC0-1.0",
            "redistribution": "allowed",
            "synthetic": True,
            "source_text_included": include_relevant,
            "generator": generator,
        }
    ]
    if "unrelated-" in context:
        provenance.append(
            {
                "source_id": distractor_id,
                "source_uri": f"synthetic://phase5/{dataset_slug}/{distractor_id}",
                "license": "CC0-1.0",
                "redistribution": "allowed",
                "synthetic": True,
                "source_text_included": True,
                "generator": generator,
            }
        )
    expected_citations = (
        [
            {
                "source_id": source_id,
                "passage_id": "chunk-0",
                "runtime_label": citation,
            }
        ]
        if citation
        else []
    )
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "example_id": f"{dataset_slug}-{task.replace('_', '-')}-{scenario.slug}-{language}-{index:03d}",
        "task": task,
        "language": language,
        "messages": [
            {"role": "system", "content": build_grounded_system_message(context)},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "expected_citations": expected_citations,
        "provenance": provenance,
        "support_review": {
            "status": "verified",
            "reviewer": "codex-production-contract-review",
            "reviewed_at": REVIEWED_AT,
            "source_ids": [item["source_id"] for item in provenance],
        },
        "sensitivity": "public",
        "approval": {
            "status": "approved",
            "reviewer": "project-owner",
            "reviewed_at": REVIEWED_AT,
            "scope": "training",
        },
        "template_family": f"production-rag-{task}-{language}-{contract_partition}-v3",
        "group_key": f"production-rag-{dataset_slug}-{task}-{scenario.slug}-{index:03d}",
        "intended_split": intended_split,
    }
    if target_schema is not None:
        record["target_json_schema"] = target_schema
    validate_target(
        record,
        incident_sections=incident_sections,
        terms=terms,
    )
    return record


def validate_target(
    record: dict[str, Any],
    *,
    incident_sections: tuple[str, ...],
    terms: tuple[str, ...],
) -> None:
    answer = record["messages"][-1]["content"]
    task = record["task"]
    language = record["language"]
    if not answer_uses_language(answer, language):
        raise ValueError(f"target language validation failed: {record['example_id']}")
    if record["expected_citations"] and not citation_format_is_valid(answer):
        raise ValueError(f"target citation validation failed: {record['example_id']}")
    if task == "json_output" and not json_answer_matches_schema(
        answer, record["target_json_schema"]
    ):
        raise ValueError(f"target JSON validation failed: {record['example_id']}")
    if task == "incident_report" and not incident_report_has_sections(
        answer, list(incident_sections)
    ):
        raise ValueError(f"target incident validation failed: {record['example_id']}")
    if task == "terminology" and not terminology_is_consistent(
        answer,
        required=[terms[0]],
        forbidden=[terms[1]],
    ):
        raise ValueError(f"target terminology validation failed: {record['example_id']}")


def write_dataset(
    *,
    output: Path,
    examples: list[dict[str, Any]],
    dataset_id: str,
    dataset_version: str,
    description: str,
    config_path: Path,
    split_percentages: tuple[int, int, int],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(example, ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    ).encode()
    (output / "examples.jsonl").write_bytes(encoded)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "description": description,
        "examples_file": "examples.jsonl",
        "examples_sha256": hashlib.sha256(encoded).hexdigest(),
        "example_schema": "../schemas/training-example-v1.schema.json",
        "template_contract": {
            "base_model_revision": config["base_model"]["revision"],
            "chat_template_sha256": config["prompt_contract"]["chat_template_sha256"],
            "max_sequence_length": config["training"]["approved_max_sequence_length"],
        },
        "split_policy": {
            "seed": config["training"]["seed"],
            "train_percent": split_percentages[0],
            "validation_percent": split_percentages[1],
            "held_out_percent": split_percentages[2],
            "group_field": "group_key",
        },
        "reserved_evaluation_datasets": [
            "evaluation/datasets/dense-baseline-v1.jsonl",
            "evaluation/datasets/phase-5-behavior-v1.jsonl",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
