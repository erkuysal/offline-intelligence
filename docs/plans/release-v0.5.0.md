# v0.5.0 Release-Closure Plan

Status: Candidate accepted locally — publication pending

## Release Scope

`v0.5.0` closes Phases 4–8 on top of the `v0.4.0` browser MVP. It preserves the accepted Gemma 3
1B Q4 CUDA runtime, permission-aware dense RAG, adapter-free production decision, network-denied
delivery, backup/restore path, and optional ABI-1 native batch-cosine component.

No new model, adapter, retrieval default, or external service is introduced during closure.

## RC0: Source and Documentation Alignment

- [x] Set live API, web, Compose, and example-environment defaults to `0.5.0`
- [x] Preserve historical `v0.4.0` and Phase 7 evidence as immutable records
- [x] Update English and Turkish current-position roadmap text
- [x] Add Phase 9 and post-Phase-9 planning entry points
- [x] Add a `v0.5.0` acceptance record populated only from final release evidence

## RC1: Reproducible Release Images and Inventories

- [ ] Build API/worker and web images as `0.5.0` from the committed source revision
- [x] Record immutable image IDs and exported archive SHA-256 values
- [x] Generate the application and web SBOMs locally without uploading private image metadata
- [x] Confirm the packaged native ABI, binary checksum, and Python fallback
- [x] Confirm build tools remain absent from runtime images

## RC2: Offline Bundle

- [x] Create a new `offline-intelligence-hub-0.5.0-linux-x86_64` specification
- [x] Refresh configuration, operator, documentation, image, inventory, and SBOM checksums
- [x] Build from the exact declared input list
- [x] Pass both the library and dependency-free operator verifiers
- [x] Preserve the accepted `0.4.0` bundle as historical evidence

## RC3: Clean Acceptance

- [x] Install into a new path-isolated target using only bundled artifacts
- [x] Exercise health, authentication, upload, ingestion, dense retrieval, grounded generation,
      citations, native loading, and deliberate Python fallback
- [x] Prove API direct egress, API DNS, and edge-web DNS remain denied
- [x] Scan runtime logs for downloads, telemetry, analytics, and external endpoints
- [x] Stop the stack without deleting target evidence or data volumes

RC3 starts both the local chat and embedding model servers. The operator must be informed before
the run begins.

## RC4: Publication

- [x] Run backend, frontend, native, documentation, and release-contract validation
- [ ] Review the final diff and acceptance evidence
- [ ] Merge the release branch through the repository's normal review path
- [ ] Create annotated tag `v0.5.0` only after every required gate passes
- [ ] Push the release commit and tag

## Definition of Done

- [x] Source, runtime metadata, image tags, bundle identity, and acceptance record all say `0.5.0`
- [x] Every shipped artifact is checksum-addressed and represented in the final inventory
- [x] The final SBOM process is local and does not disclose private image metadata
- [x] A clean air-gapped target passes the complete product and native-fallback paths
- [ ] The committed and tagged release is reproducible from documented inputs
