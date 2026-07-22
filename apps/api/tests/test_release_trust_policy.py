from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import manage
from delivery.trust_policy import ReleaseTrustPolicy, load_release_trust_policy


ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "config" / "supply-chain" / "release-trust-policy-v1.json"


def test_phase_9_trust_policy_has_required_zones_assets_and_failures() -> None:
    policy = load_release_trust_policy(POLICY_PATH)

    assert {zone.zone_id for zone in policy.zones} == {
        "connected_builder",
        "disconnected_target",
        "transfer_media",
        "trust_administration",
    }
    assets = {asset.asset_id: asset for asset in policy.assets}
    assert assets["release_signing_private_key"].distribution == "builder_only"
    assert assets["release_trust_root"].distribution == "out_of_band_trust_store"
    assert all(
        asset.classification not in {"secret", "confidential"}
        for asset in policy.assets
        if asset.distribution == "bundle"
    )
    assert all(
        rule.action == "reject_before_mutation"
        for rule in policy.failure_rules
        if rule.stage == "pre_install"
    )


def test_policy_rejects_private_key_distribution_in_bundle() -> None:
    payload = load_release_trust_policy(POLICY_PATH).model_dump(mode="json")
    private_key = next(
        asset for asset in payload["assets"] if asset["asset_id"] == "release_signing_private_key"
    )
    private_key["distribution"] = "bundle"

    with pytest.raises(ValueError, match="builder-only"):
        ReleaseTrustPolicy.model_validate(payload)


def test_policy_rejects_missing_mandatory_failure_rule() -> None:
    payload = load_release_trust_policy(POLICY_PATH).model_dump(mode="json")
    payload["failure_rules"] = [
        rule
        for rule in payload["failure_rules"]
        if rule["condition"] != "payload_integrity_failure"
    ]

    with pytest.raises(ValueError, match="payload_integrity_failure"):
        ReleaseTrustPolicy.model_validate(payload)


def test_trust_policy_cli_accepts_checked_in_policy() -> None:
    status = manage.release_trust_policy_verify(argparse.Namespace(policy=str(POLICY_PATH)))

    assert status == 0
