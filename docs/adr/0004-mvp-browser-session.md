# ADR 0004: MVP Browser Session Storage

## Status

Accepted for the `v0.4.0` local/on-premise MVP

## Context

The Vue client needs to restore authenticated sessions and renew short-lived access tokens. The
current API returns access and refresh tokens in JSON and uses stateless signed JWTs. The initial
target is a locally operated or trusted on-premise deployment, not unrestricted public hosting.

## Decision

- Keep access and refresh tokens in browser session storage for the `v0.4.0` MVP.
- Retry a protected request only once after a `401` response.
- Deduplicate concurrent refresh attempts in the client.
- Rotate both tokens after a successful refresh.
- Clear both tokens when refresh fails, a retried request is still unauthorized, or the user logs
  out.
- Do not claim individual refresh-token revocation: the current JWT design is stateless and has no
  server-side session or deny-list record.
- Require secure HTTP-only, SameSite cookies and server-side refresh-session revocation before
  public hosting or a broader multi-user security posture is accepted.

## Consequences

- Closing the browser tab ends the stored browser session.
- Session storage keeps credentials out of persistent local storage but remains accessible to
  JavaScript; preventing cross-site scripting remains security-critical.
- Logout clears browser credentials but cannot invalidate a copied refresh token before its expiry.
- Refresh-token lifetime remains the upper bound for exposure until server-side revocation exists.
- Moving to cookies will require CSRF protections, cookie-aware API configuration, and updated
  browser tests.
