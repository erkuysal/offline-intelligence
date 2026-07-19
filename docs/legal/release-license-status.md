# Release License Status

This repository does not currently declare a top-level project license. Redistribution approval
for the application must therefore be established by the release owner before a bundle is
transferred outside the authorized environment.

Third-party package names, versions, declared licenses, and source metadata are recorded in the
SPDX image inventories shipped under `sbom/`. Those inventories support review; they do not replace
the corresponding upstream license texts or legal approval.

For the Phase 7 barebones internal delivery path:

- keep the SPDX inventories with every transferred bundle;
- limit transfer to the environment and recipients authorized by the release owner;
- resolve `NOASSERTION` and missing-license entries before external redistribution; and
- add a project `LICENSE` plus a reviewed third-party notices set before public distribution.

This file is an engineering status record, not legal advice or a grant of rights.
