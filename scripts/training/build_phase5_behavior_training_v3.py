#!/usr/bin/env python3
from __future__ import annotations

from phase5_v3_contract import ROOT, TASKS, Scenario, build_example, write_dataset


OUTPUT = ROOT / "training" / "datasets" / "phase5-behavior-training-v3"
CONFIG = ROOT / "config" / "training" / "gemma3-1b-lora-v3.json"
PREFIXES = (
    "Aster",
    "Birch",
    "Coral",
    "Delta",
    "Ember",
    "Flint",
    "Grove",
    "Harbor",
    "Iris",
    "Juniper",
)
COMPONENTS = ("relay", "ledger", "beacon", "index", "worker")
OWNERS_EN = ("platform team", "records team", "network team", "search team", "operations team")
OWNERS_TR = ("platform ekibi", "kayıt ekibi", "ağ ekibi", "arama ekibi", "operasyon ekibi")
TERMS_EN = ("recovery checkpoint", "routing window", "retention cycle", "index horizon", "execution policy")
TERMS_TR = ("kurtarma kontrol noktası", "yönlendirme aralığı", "saklama döngüsü", "dizin ufku", "çalıştırma politikası")


def scenario(index: int) -> Scenario:
    prefix = PREFIXES[index // 5]
    component = COMPONENTS[index % 5]
    hour = (index * 5 + 2) % 24
    minute = (index * 13 + 7) % 60
    incident_hour = (hour + 3) % 24
    start = f"{incident_hour:02d}:{minute:02d} UTC"
    end = f"{incident_hour:02d}:{(minute + 11) % 60:02d} UTC"
    return Scenario(
        slug=f"{prefix.casefold()}-{component}",
        name_en=f"{prefix} {component}",
        name_tr=f"{prefix} {component}",
        filename_en=f"{prefix.casefold()}-{component}-en.txt",
        filename_tr=f"{prefix.casefold()}-{component}-tr.txt",
        status_en="ready",
        status_tr="hazırdır",
        interval_minutes=5 + index % 25,
        window=f"{hour:02d}:{minute:02d} UTC",
        owner_en=OWNERS_EN[index % 5],
        owner_tr=OWNERS_TR[index % 5],
        term_en=TERMS_EN[index % 5],
        term_tr=TERMS_TR[index % 5],
        deprecated_en="legacy marker",
        deprecated_tr="eski işaret",
        incident_start=start,
        incident_end=end,
        cause_en="a synthetic routing rule loaded late",
        cause_tr="sentetik yönlendirme kuralı geç yüklendi",
        action_en="The operator restored the previous route set",
        action_tr="Operatör önceki rota kümesini geri yükledi",
    )


def main() -> None:
    examples = [
        build_example(
            task=task,
            language=language,
            index=index,
            scenario=scenario(index),
            intended_split="train" if index < 40 else "validation",
            dataset_slug="train-v3",
            generator="phase5-production-contract-training-v3",
        )
        for task in TASKS
        for language in ("en", "tr")
        for index in range(50)
    ]
    write_dataset(
        output=OUTPUT,
        examples=examples,
        dataset_id="phase5-behavior-training",
        dataset_version="3.0.0",
        description="Production-RAG-contract bilingual SFT corpus with natural-answer retention",
        config_path=CONFIG,
        split_percentages=(80, 10, 10),
    )
    print(f"wrote {len(examples)} examples to {OUTPUT}")


if __name__ == "__main__":
    main()
