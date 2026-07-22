from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


REQUIRED_FAILURE_CONDITIONS = {
    "missing_signature",
    "unknown_signing_key",
    "revoked_signing_key",
    "mismatched_release_identity",
    "manifest_integrity_failure",
    "payload_integrity_failure",
    "missing_provenance",
    "sbom_identity_mismatch",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrustZone(StrictModel):
    zone_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connectivity: Literal["connected", "transfer_only", "disconnected", "out_of_band"]
    trusted_for: list[str] = Field(min_length=1)
    prohibited_actions: list[str] = Field(default_factory=list)


class TrustAsset(StrictModel):
    asset_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    classification: Literal["public", "internal", "confidential", "secret"]
    distribution: Literal[
        "builder_only",
        "bundle",
        "target_only",
        "out_of_band_trust_store",
    ]
    integrity_required: bool
    confidentiality_required: bool
    authority: str = Field(min_length=1)


class FailureRule(StrictModel):
    condition: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    stage: Literal["build", "transfer", "pre_install", "runtime", "upgrade"]
    action: Literal["reject_before_mutation", "halt", "restore_required"]
    required_evidence: list[str] = Field(min_length=1)


class ReleaseTrustPolicy(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_type: Literal["offline_release_trust_policy"] = "offline_release_trust_policy"
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    zones: list[TrustZone] = Field(min_length=1)
    assets: list[TrustAsset] = Field(min_length=1)
    failure_rules: list[FailureRule] = Field(min_length=1)
    pre_mutation_operations: list[str] = Field(min_length=1)
    prohibited_before_verification: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_trust_boundary(self) -> Self:
        zone_ids = [zone.zone_id for zone in self.zones]
        asset_ids = [asset.asset_id for asset in self.assets]
        conditions = [rule.condition for rule in self.failure_rules]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("trust zone IDs must be unique")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("trust asset IDs must be unique")
        if len(conditions) != len(set(conditions)):
            raise ValueError("failure conditions must be unique")

        assets = {asset.asset_id: asset for asset in self.assets}
        private_key = assets.get("release_signing_private_key")
        trust_root = assets.get("release_trust_root")
        if private_key is None or private_key.classification != "secret":
            raise ValueError("release_signing_private_key must be classified as secret")
        if private_key.distribution != "builder_only":
            raise ValueError("release_signing_private_key must remain builder-only")
        if trust_root is None or trust_root.distribution != "out_of_band_trust_store":
            raise ValueError("release_trust_root must be provisioned out of band")
        if any(
            asset.distribution == "bundle" and asset.classification in {"secret", "confidential"}
            for asset in self.assets
        ):
            raise ValueError("secret or confidential assets must not be shipped in the bundle")

        missing_conditions = sorted(REQUIRED_FAILURE_CONDITIONS - set(conditions))
        if missing_conditions:
            raise ValueError(
                "trust policy is missing mandatory failure conditions: "
                + ", ".join(missing_conditions)
            )
        pre_install_rules = [rule for rule in self.failure_rules if rule.stage == "pre_install"]
        if any(rule.action != "reject_before_mutation" for rule in pre_install_rules):
            raise ValueError("every pre-install trust failure must reject before mutation")
        return self


def load_release_trust_policy(path: Path) -> ReleaseTrustPolicy:
    return ReleaseTrustPolicy.model_validate_json(path.read_text(encoding="utf-8"))
