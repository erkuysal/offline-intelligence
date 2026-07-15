# Technical Vision Versions

Technical visions are versioned so the architecture can evolve without rewriting the historical
intent, boundaries, and promotion criteria used by an earlier product generation.

## Available Versions

| Version | Status | Scope |
| --- | --- | --- |
| [v1](v1/README.md) | Active | Product foundation through planned native acceleration, Phases 1–8 |

## Versioning Policy

- A version describes one coherent product architecture and phase sequence.
- Clarifications and corrections that do not change architectural intent stay within the same
  version.
- Material changes to system boundaries, phase responsibilities, security assumptions, or the
  target architecture require a new version directory.
- Older versions remain available as historical records after a newer version becomes active.
- Plans, ADRs, and acceptance records remain independently dated and versioned evidence; technical
  vision versions link to them rather than replacing them.

The current entry point is [Technical Vision v1](v1/README.md).
