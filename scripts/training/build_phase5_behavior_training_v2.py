#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "training" / "datasets" / "phase5-behavior-training-v2"
CONFIG_PATH = ROOT / "config" / "training" / "gemma3-1b-lora-v2.json"
REVIEWED_AT = "2026-07-17T12:00:00+03:00"

PREFIXES = (
    "Amber",
    "Boreal",
    "Cinder",
    "Dawn",
    "Elm",
    "Fable",
    "Glacier",
    "Hazel",
    "Indigo",
    "Jade",
)
EN_NOUNS = ("queue", "archive", "gateway", "catalog", "scheduler")
TR_NOUNS = ("kuyruğu", "arşivi", "ağ geçidi", "kataloğu", "zamanlayıcısı")
EN_OWNERS = (
    "platform team",
    "records team",
    "network team",
    "content team",
    "automation team",
    "reliability team",
    "release team",
    "storage team",
    "search team",
    "operations team",
)
TR_OWNERS = (
    "platform ekibi",
    "kayıt ekibi",
    "ağ ekibi",
    "içerik ekibi",
    "otomasyon ekibi",
    "güvenilirlik ekibi",
    "sürüm ekibi",
    "depolama ekibi",
    "arama ekibi",
    "operasyon ekibi",
)
EN_TERMS = (
    "routing window",
    "retention cycle",
    "traffic policy",
    "publication window",
    "execution cycle",
)
TR_TERMS = (
    "yönlendirme aralığı",
    "saklama döngüsü",
    "trafik politikası",
    "yayın aralığı",
    "çalıştırma döngüsü",
)
EN_CAUSES = (
    "an upstream dependency responded late",
    "a queue lock remained active",
    "a validation job exceeded its time budget",
    "a routing rule loaded slowly",
    "a storage check required a retry",
)
TR_CAUSES = (
    "üst bağımlılık geç yanıt verdi",
    "bir kuyruk kilidi etkin kaldı",
    "doğrulama işi süre sınırını aştı",
    "yönlendirme kuralı yavaş yüklendi",
    "depolama denetimi yeniden deneme gerektirdi",
)
TASKS = (
    "grounded_answer",
    "grounded_refusal",
    "citation_formatting",
    "json_output",
    "incident_report",
    "terminology",
)


def split_for(index: int) -> str:
    if index < 35:
        return "train"
    if index < 40:
        return "validation"
    return "held_out"


def scenario(index: int, language: str) -> dict[str, str]:
    prefix = PREFIXES[index // 5]
    noun_index = index % 5
    hour = (index * 7 + 3) % 24
    minute = (index * 11 + 5) % 60
    return {
        "slug": f"{prefix.casefold()}-{EN_NOUNS[noun_index]}",
        "name": f"{prefix} {(TR_NOUNS if language == 'tr' else EN_NOUNS)[noun_index]}",
        "window": f"{hour:02d}:{minute:02d} UTC",
        "owner": (TR_OWNERS if language == "tr" else EN_OWNERS)[index % 10],
        "term": (TR_TERMS if language == "tr" else EN_TERMS)[noun_index],
        "cause": (TR_CAUSES if language == "tr" else EN_CAUSES)[index % 5],
        "delay": str(4 + index % 17),
    }


def source_text(values: dict[str, str], language: str, layout: int) -> str:
    if language == "en":
        variants = (
            f"Source excerpt: {values['name']} runs at {values['window']}. The {values['owner']} owns it. Its canonical term is '{values['term']}'.",
            f"Operations record\nservice={values['name']}\nrun window={values['window']}\nowner={values['owner']}\ncanonical term={values['term']}",
            f"Verified facts:\n- Service: {values['name']}\n- Scheduled time: {values['window']}\n- Responsible group: {values['owner']}\n- Required term: {values['term']}",
            f"Policy note: Use '{values['term']}' for {values['name']}. It is maintained by the {values['owner']} and starts at {values['window']}.",
            f"The synthetic runbook assigns {values['name']} to the {values['owner']}; the scheduled start is {values['window']}, and '{values['term']}' is the approved wording.",
        )
    else:
        variants = (
            f"Kaynak alıntısı: {values['name']} saat {values['window']}'de çalışır. Sorumlusu {values['owner']}. Standart terim '{values['term']}'.",
            f"Operasyon kaydı\nhizmet={values['name']}\nçalışma saati={values['window']}\nsorumlu={values['owner']}\nstandart terim={values['term']}",
            f"Doğrulanmış bilgiler:\n- Hizmet: {values['name']}\n- Planlanan saat: {values['window']}\n- Sorumlu grup: {values['owner']}\n- Zorunlu terim: {values['term']}",
            f"Politika notu: {values['name']} için '{values['term']}' kullanılır. {values['owner']} tarafından yönetilir ve saat {values['window']}'de başlar.",
            f"Sentetik çalışma kılavuzu {values['name']} hizmetini {values['owner']} sorumluluğuna verir; başlangıç saati {values['window']}, onaylı ifade ise '{values['term']}' terimidir.",
        )
    return variants[layout]


def metadata(
    *, example_id: str, task: str, language: str, source_id: str, split: str, layout: int
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
                "source_uri": f"synthetic://phase5-training-v2/{source_id}",
                "license": "CC0-1.0",
                "redistribution": "allowed",
                "synthetic": True,
                "source_text_included": True,
                "generator": "codex-gpt-5-project-authored-v2",
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
        "template_family": f"{task}-{language}-{split}-layout-{layout}-v2",
        "group_key": example_id,
        "intended_split": split,
    }


def json_schema(language: str) -> dict[str, Any]:
    if language == "en":
        fields = ("service", "run_window", "owner", "status")
        status_field, status = "status", "operational"
    else:
        fields = ("hizmet", "çalışma_saati", "sorumlu", "durum")
        status_field, status = "durum", "çalışıyor"
    properties: dict[str, Any] = {field: {"type": "string"} for field in fields}
    properties[status_field]["enum"] = [status]
    return {
        "type": "object",
        "required": list(fields),
        "properties": properties,
        "additionalProperties": False,
    }


def build_example(task: str, language: str, index: int) -> dict[str, Any]:
    values = scenario(index, language)
    split = split_for(index)
    layout = index % 5
    source_id = f"doc-{values['slug']}-{language}"
    passage_id = f"p-{index + 1:03d}"
    citation = f"[{source_id}#{passage_id}]"
    example_id = f"{language}-{task.replace('_', '-')}-{values['slug']}-{index + 1:03d}-v2"
    record = metadata(
        example_id=example_id,
        task=task,
        language=language,
        source_id=source_id,
        split=split,
        layout=layout,
    )
    source = source_text(values, language, layout)
    if language == "en":
        system = "Use only the supplied synthetic source and obey the requested response contract."
        if task == "grounded_answer":
            questions = (
                "State the scheduled time and owner. End with the exact supplied source marker.",
                "Who owns this service, and when does it run? Cite the provided passage exactly.",
                "Answer the schedule question in one sourced sentence.",
                "Using only the policy note, report the owner and start time with its citation.",
                "Give a concise grounded answer for time and responsibility; preserve the citation ID.",
            )
            user = f"{source}\n\nAvailable source marker: {citation}\n{questions[layout]}"
            assistant = f"{values['name']} runs at {values['window']} and is owned by the {values['owner']}. {citation}"
        elif task == "grounded_refusal":
            user = f"{source}\n\nWhat is the escalation contact and telephone extension?"
            assistant = "I do not have enough information in the supplied source to answer that question."
        elif task == "citation_formatting":
            requests = (
                "Return one concise sentence with the exact bracketed document and passage citation.",
                "Rewrite the verified schedule and owner, preserving the source identifier exactly.",
                "Format a grounded answer and finish it with the required [document#passage] marker.",
                "Cite the policy claim using the provided source and passage IDs, without a web link.",
                "Produce the sourced statement only; use the project's bracket citation syntax.",
            )
            user = f"{source}\n\nRequired marker: {citation}\n{requests[layout]}"
            assistant = f"The {values['owner']} maintains {values['name']}, which runs at {values['window']}. {citation}"
        elif task == "json_output":
            user = f"{source}\n\nReturn only a JSON object with service, run_window, owner, and status. Do not use Markdown fences."
            assistant = json.dumps(
                {
                    "service": values["name"],
                    "run_window": values["window"],
                    "owner": values["owner"],
                    "status": "operational",
                },
                separators=(",", ":"),
            )
            record["target_json_schema"] = json_schema(language)
        elif task == "incident_report":
            user = (
                f"{source}\n\n{values['name']} started {values['delay']} minutes late because {values['cause']}. "
                f"Processing was delayed but no records were lost. The {values['owner']} restored the schedule. "
                "Return exactly four concise sections named Summary, Impact, Cause, and Action. Do not use JSON."
            )
            assistant = (
                f"Summary: {values['name']} started {values['delay']} minutes late.\n"
                "Impact: Processing was delayed; no records were lost.\n"
                f"Cause: {values['cause'].capitalize()}.\n"
                f"Action: The {values['owner']} restored the schedule and will monitor the next run."
            )
        else:
            user = f"{source}\n\nUse the exact canonical term '{values['term']}' in one sentence. Do not use 'legacy interval'."
            assistant = f"The {values['term']} for {values['name']} begins at {values['window']} and is maintained by the {values['owner']}."
    else:
        system = "Yalnızca verilen sentetik kaynağı kullan ve istenen yanıt sözleşmesine uy."
        if task == "grounded_answer":
            questions = (
                "Planlanan saati ve sorumlu ekibi belirt. Tam kaynak işaretiyle bitir.",
                "Bu hizmeti kim yönetir ve hizmet ne zaman çalışır? Verilen bölüme tam olarak atıf yap.",
                "Çalışma saati sorusunu kaynaklı tek cümleyle yanıtla.",
                "Yalnızca politika notunu kullanarak sorumluyu ve saati atıfla bildir.",
                "Saat ve sorumluluk için kısa bir yanıt ver; atıf kimliğini aynen koru.",
            )
            user = f"{source}\n\nKullanılabilir kaynak işareti: {citation}\n{questions[layout]}"
            assistant = f"{values['name']} saat {values['window']}'de çalışır ve {values['owner']} tarafından yönetilir. {citation}"
        elif task == "grounded_refusal":
            user = f"{source}\n\nYükseltme irtibatı ve telefon dahili numarası nedir?"
            assistant = "Bu soruyu yanıtlamak için verilen kaynakta yeterli bilgi bulunmuyor."
        elif task == "citation_formatting":
            requests = (
                "Tam belge ve bölüm atfıyla kısa bir cümle döndür.",
                "Doğrulanmış saati ve sorumluyu kaynak kimliğini aynen koruyarak yeniden yaz.",
                "Kaynaklı yanıtı zorunlu [belge#bölüm] işaretiyle bitir.",
                "Politika iddiasına verilen kaynak ve bölüm kimliğiyle atıf yap; web bağlantısı kullanma.",
                "Yalnızca kaynaklı ifadeyi üret ve projenin köşeli parantez atıf biçimini kullan.",
            )
            user = f"{source}\n\nZorunlu işaret: {citation}\n{requests[layout]}"
            assistant = f"{values['name']}, {values['owner']} sorumluluğunda saat {values['window']}'de çalışır. {citation}"
        elif task == "json_output":
            user = f"{source}\n\nYalnızca hizmet, çalışma_saati, sorumlu ve durum alanlı JSON nesnesi döndür. Markdown çiti kullanma."
            assistant = json.dumps(
                {
                    "hizmet": values["name"],
                    "çalışma_saati": values["window"],
                    "sorumlu": values["owner"],
                    "durum": "çalışıyor",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            record["target_json_schema"] = json_schema(language)
        elif task == "incident_report":
            user = (
                f"{source}\n\n{values['name']}, {values['cause']} nedeniyle {values['delay']} dakika geç başladı. "
                f"İşleme gecikti ancak kayıt kaybı olmadı. {values['owner']} düzeni geri yükledi. "
                "Tam olarak Özet, Etki, Neden ve Eylem adlı dört kısa bölüm döndür. JSON kullanma."
            )
            assistant = (
                f"Özet: {values['name']} {values['delay']} dakika geç başladı.\n"
                "Etki: İşleme gecikti; kayıt kaybı olmadı.\n"
                f"Neden: {values['cause'].capitalize()}.\n"
                f"Eylem: {values['owner']} düzeni geri yükledi ve sonraki çalışmayı izleyecek."
            )
        else:
            user = f"{source}\n\nTam standart terim '{values['term']}' ifadesini tek cümlede kullan. 'Eski periyot' deme."
            assistant = f"{values['name']} için {values['term']} saat {values['window']}'de başlar ve {values['owner']} tarafından yönetilir."
    record["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]
    if task in {"grounded_answer", "citation_formatting"}:
        record["expected_citations"] = [
            {"source_id": source_id, "passage_id": passage_id}
        ]
    return record


def main() -> None:
    examples = [
        build_example(task, language, index)
        for task in TASKS
        for language in ("en", "tr")
        for index in range(50)
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(example, ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    ).encode()
    (OUTPUT / "examples.jsonl").write_bytes(encoded)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "phase5-behavior-training",
        "dataset_version": "2.0.1",
        "description": "Expanded bilingual synthetic behavior corpus with production-shaped citations, varied source layouts, and larger development slices",
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
