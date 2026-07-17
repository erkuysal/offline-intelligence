#!/usr/bin/env python3
from __future__ import annotations

from phase5_v3_contract import ROOT, TASKS, Scenario, build_example, write_dataset


OUTPUT = ROOT / "training" / "datasets" / "phase5-behavior-development-v3"
CONFIG = ROOT / "config" / "training" / "gemma3-1b-lora-v3.json"
NAMES = (
    "Lumen console", "Mosaic queue", "Nectar registry", "Onyx bridge", "Prairie cache",
    "Quill monitor", "Raven spool", "Saffron router", "Tundra journal", "Umber proxy",
    "Vale catalog", "Willow runner", "Xenon gateway", "Yarrow broker", "Zephyr archive",
    "Acorn scheduler", "Brook index", "Cedar relay", "Dune ledger", "Echo beacon",
)


def development_scenario(index: int) -> Scenario:
    name = NAMES[index]
    slug = name.replace(" ", "-").casefold()
    hour = (index * 7 + 1) % 24
    minute = (index * 17 + 9) % 60
    return Scenario(
        slug=slug,
        name_en=name,
        name_tr=name,
        filename_en=f"{slug}-evidence-en.txt",
        filename_tr=f"{slug}-kanit-tr.txt",
        status_en="ready",
        status_tr="hazırdır",
        interval_minutes=31 + index,
        window=f"{hour:02d}:{minute:02d} UTC",
        owner_en=("assurance team", "capacity team", "delivery team", "observability team")[index % 4],
        owner_tr=("güvence ekibi", "kapasite ekibi", "teslimat ekibi", "gözlemlenebilirlik ekibi")[index % 4],
        term_en=("recovery coordinate", "routing interval", "retention boundary", "execution checkpoint")[index % 4],
        term_tr=("kurtarma koordinatı", "yönlendirme aralığı", "saklama sınırı", "çalıştırma kontrol noktası")[index % 4],
        deprecated_en="obsolete pointer",
        deprecated_tr="eski gösterge",
        incident_start=f"{(hour + 4) % 24:02d}:{minute:02d} UTC",
        incident_end=f"{(hour + 4) % 24:02d}:{(minute + 8) % 60:02d} UTC",
        cause_en="a synthetic dependency exceeded its response budget",
        cause_tr="sentetik bağımlılık yanıt süresini aştı",
        action_en="The operator reverted the dependency route",
        action_tr="Operatör bağımlılık rotasını geri aldı",
    )


def main() -> None:
    examples = [
        build_example(
            task=task,
            language=language,
            index=index + 100,
            scenario=development_scenario(index),
            intended_split="held_out",
            dataset_slug="dev-v3",
            generator="independently-authored-production-contract-development-v3",
        )
        for task in TASKS
        for language in ("en", "tr")
        for index in range(20)
    ]
    write_dataset(
        output=OUTPUT,
        examples=examples,
        dataset_id="phase5-behavior-development",
        dataset_version="3.0.0",
        description="Independent production-contract bilingual development proxy; never used for optimization",
        config_path=CONFIG,
        split_percentages=(10, 10, 80),
    )
    print(f"wrote {len(examples)} examples to {OUTPUT}")


if __name__ == "__main__":
    main()
