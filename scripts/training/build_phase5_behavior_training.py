#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "training" / "datasets" / "phase5-behavior-training-v1"
REVIEWED_AT = "2026-07-16T12:00:00+03:00"

SCENARIOS = (
    ("atlas", "Atlas queue", "Atlas kuyruğu", "05:20 UTC", "platform team", "platform ekibi", "routing window", "yönlendirme aralığı"),
    ("birch", "Birch archive", "Huş arşivi", "22:15 UTC", "records team", "kayıt ekibi", "retention window", "saklama aralığı"),
    ("cobalt", "Cobalt index", "Kobalt dizini", "03:45 UTC", "search team", "arama ekibi", "refresh cycle", "yenileme döngüsü"),
    ("delta", "Delta gateway", "Delta ağ geçidi", "11:30 UTC", "network team", "ağ ekibi", "traffic policy", "trafik politikası"),
    ("ember", "Ember ledger", "Kor defteri", "18:05 UTC", "finance operations", "finans operasyonları", "reconciliation cycle", "mutabakat döngüsü"),
    ("fjord", "Fjord catalog", "Fiyort kataloğu", "07:50 UTC", "content team", "içerik ekibi", "publication window", "yayın aralığı"),
    ("garnet", "Garnet monitor", "Lal monitörü", "14:25 UTC", "reliability team", "güvenilirlik ekibi", "alert policy", "uyarı politikası"),
    ("harbor", "Harbor registry", "Liman kayıt sistemi", "01:10 UTC", "release team", "sürüm ekibi", "release channel", "sürüm kanalı"),
    ("iris", "Iris scheduler", "İris zamanlayıcısı", "09:35 UTC", "automation team", "otomasyon ekibi", "execution window", "çalıştırma aralığı"),
    ("juniper", "Juniper vault", "Ardıç kasası", "16:40 UTC", "storage team", "depolama ekibi", "backup cycle", "yedekleme döngüsü"),
)


def split_for(index: int) -> str:
    if index < 7:
        return "train"
    if index == 7:
        return "validation"
    return "held_out"


def shared_metadata(
    *, example_id: str, task: str, language: str, source_id: str, split: str
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "example_id": example_id,
        "task": task,
        "language": language,
        "expected_citations": [],
        "provenance": [
            {
                "source_id": source_id,
                "source_uri": f"synthetic://phase5-training-v1/{source_id}",
                "license": "CC0-1.0",
                "redistribution": "allowed",
                "synthetic": True,
                "source_text_included": True,
                "generator": "codex-gpt-5-project-authored-v1",
            }
        ],
        "support_review": {
            "status": "verified",
            "reviewer": "codex-data-support-review",
            "reviewed_at": REVIEWED_AT,
            "source_ids": [source_id],
        },
        "sensitivity": "public",
        "approval": {
            "status": "approved",
            "reviewer": "project-owner",
            "reviewed_at": REVIEWED_AT,
            "scope": "training",
        },
        "template_family": f"{task}-{language}-{split}-v1",
        "group_key": example_id,
        "intended_split": split,
    }


def build_example(task: str, language: str, index: int) -> dict[str, Any]:
    slug, en_name, tr_name, window, en_owner, tr_owner, en_term, tr_term = SCENARIOS[index]
    split = split_for(index)
    source_id = f"train-{language}-{task.replace('_', '-')}-{slug}"
    example_id = f"{language}-{task.replace('_', '-')}-{slug}-v1"
    record = shared_metadata(
        example_id=example_id,
        task=task,
        language=language,
        source_id=source_id,
        split=split,
    )
    citation = f"[{source_id}#facts]"
    if language == "en":
        name, owner, term = en_name, en_owner, en_term
        source = (
            f"Synthetic source facts: {name} runs at {window}, is owned by the {owner}, "
            f"and uses the canonical term '{term}'."
        )
        system = "Use only the supplied synthetic source. Follow the requested output format."
        if task == "grounded_answer":
            user = f"{source}\nWhen does {name} run, and which team owns it?"
            assistant = f"{name} runs at {window} and is owned by the {owner}. {citation}"
        elif task == "grounded_refusal":
            user = f"{source}\nWhat is the escalation contact for {name}?"
            assistant = "I do not have enough information in the supplied source to answer that question."
        elif task == "citation_formatting":
            user = f"{source}\nRewrite the schedule and owner as one concise answer with a source citation."
            assistant = f"The {owner} owns {name}, which runs at {window}. {citation}"
        elif task == "json_output":
            user = f"{source}\nReturn only JSON with service, run_window, owner, and status."
            assistant = json.dumps(
                {"service": name, "run_window": window, "owner": owner, "status": "operational"},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            record["target_json_schema"] = json_schema("operational")
        elif task == "incident_report":
            user = (
                f"{source}\nA delayed dependency made {name} start twelve minutes late. "
                f"No records were lost, and the {owner} restored the normal schedule. Write a brief incident report."
            )
            assistant = (
                f"Summary: {name} started twelve minutes late.\n"
                "Impact: Processing was delayed; no records were lost.\n"
                "Cause: An upstream dependency was delayed.\n"
                f"Action: The {owner} restored the normal schedule and will monitor the next run."
            )
        else:
            user = (
                f"{source}\nDescribe the operating rule in one sentence. Use the exact canonical term "
                f"'{term}' and do not use 'legacy interval'."
            )
            assistant = f"The {term} for {name} begins at {window} and is maintained by the {owner}."
    else:
        name, owner, term = tr_name, tr_owner, tr_term
        source = (
            f"Sentetik kaynak bilgileri: {name} saat {window}'de çalışır, sahibi {owner} ve "
            f"standart terim '{term}' olarak belirlenmiştir."
        )
        system = "Yalnızca verilen sentetik kaynağı kullan. İstenen çıktı biçimine uy."
        if task == "grounded_answer":
            user = f"{source}\n{name} ne zaman çalışır ve hangi ekip tarafından yönetilir?"
            assistant = f"{name} saat {window}'de çalışır ve {owner} tarafından yönetilir. {citation}"
        elif task == "grounded_refusal":
            user = f"{source}\n{name} için yükseltme irtibatı kimdir?"
            assistant = "Bu soruyu yanıtlamak için verilen kaynakta yeterli bilgi bulunmuyor."
        elif task == "citation_formatting":
            user = f"{source}\nÇalışma saatini ve sorumlu ekibi kaynak atıflı tek bir cümleyle yaz."
            assistant = f"{name}, {owner} sorumluluğunda saat {window}'de çalışır. {citation}"
        elif task == "json_output":
            user = f"{source}\nYalnızca hizmet, çalışma_saati, sorumlu ve durum alanlarını içeren JSON döndür."
            assistant = json.dumps(
                {"hizmet": name, "çalışma_saati": window, "sorumlu": owner, "durum": "çalışıyor"},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            record["target_json_schema"] = json_schema("çalışıyor", turkish=True)
        elif task == "incident_report":
            user = (
                f"{source}\nGeciken bir bağımlılık nedeniyle {name} on iki dakika geç başladı. "
                f"Kayıt kaybı olmadı ve {owner} normal düzeni geri yükledi. Kısa bir olay raporu yaz."
            )
            assistant = (
                f"Özet: {name} on iki dakika geç başladı.\n"
                "Etki: İşleme gecikti; kayıt kaybı olmadı.\n"
                "Neden: Üst bağımlılık gecikti.\n"
                f"Eylem: {owner} normal düzeni geri yükledi ve sonraki çalışmayı izleyecek."
            )
        else:
            user = (
                f"{source}\nİşletim kuralını tek cümleyle açıkla. Tam olarak '{term}' terimini kullan "
                "ve 'eski periyot' ifadesini kullanma."
            )
            assistant = f"{name} için {term} saat {window}'de başlar ve {owner} tarafından yönetilir."
    record["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]
    if task in {"grounded_answer", "citation_formatting"}:
        record["expected_citations"] = [{"source_id": source_id, "passage_id": "facts"}]
    return record


def json_schema(status: str, *, turkish: bool = False) -> dict[str, Any]:
    fields = (
        {"hizmet": "string", "çalışma_saati": "string", "sorumlu": "string", "durum": "string"}
        if turkish
        else {"service": "string", "run_window": "string", "owner": "string", "status": "string"}
    )
    status_field = "durum" if turkish else "status"
    properties: dict[str, Any] = {key: {"type": kind} for key, kind in fields.items()}
    properties[status_field]["enum"] = [status]
    return {
        "type": "object",
        "required": list(fields),
        "properties": properties,
        "additionalProperties": False,
    }


def main() -> None:
    tasks = (
        "grounded_answer",
        "grounded_refusal",
        "citation_formatting",
        "json_output",
        "incident_report",
        "terminology",
    )
    examples = [
        build_example(task, language, index)
        for task in tasks
        for language in ("en", "tr")
        for index in range(len(SCENARIOS))
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(example, ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    ).encode()
    (OUTPUT / "examples.jsonl").write_bytes(encoded)
    config = json.loads((ROOT / "config/training/gemma3-1b-lora-v1.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "phase5-behavior-training",
        "dataset_version": "1.0.0",
        "description": "Project-owner-authorized bilingual synthetic behavior training corpus; separate from protected evaluation evidence",
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
            "train_percent": 70,
            "validation_percent": 10,
            "held_out_percent": 20,
            "group_field": "group_key",
        },
        "reserved_evaluation_datasets": [
            "evaluation/datasets/dense-baseline-v1.jsonl",
            "evaluation/datasets/phase-5-behavior-v1.jsonl",
        ],
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(examples)} examples to {OUTPUT}")


if __name__ == "__main__":
    main()
