# ADR-013: The Ask MIZAN endpoint is origin-guarded, not authenticated

- **Status:** Accepted with a stated limitation (2026-11-17)
- **Date:** 2026-11-17
- **Supersedes:** nothing. Extends ADR-012, which left this gap open.

## Context

ADR-012 put the agent behind one Azure Function whose managed identity reaches Azure OpenAI with no key
anywhere. It did not answer the next question a reviewer asks: **who may call that Function?**

Today the answer is an `Origin` check plus rate limits (20/minute, 600/day) and a USD 5 budget alert.
An `Origin` header is set by the browser but trivially forged by anything that is not a browser, so the
guard raises the cost of abuse without preventing it. The exposure is bounded -- the Function reads no
Fabric data and holds no secret, the tools run in the caller's browser under the caller's own Fabric
permissions, and the worst case is someone spending the owner's Azure credit -- but it is not access
control, and HONESTY.md should not imply otherwise.

The obvious fix is App Service / Functions built-in authentication (Easy Auth) with Microsoft Entra,
set to "require authentication" and restricted to a tenant.

## Decision

**Keep the origin guard. Do not add Easy Auth.** Three reasons, in order of weight:

1. **The two tenants are different.** Fabric lives in the college tenant
   (`shadink1244.2021@hinducollege.ac.in`); the Function lives in the owner's personal subscription.
   Tenant-restricting the Function to the college tenant would require app-registration rights the
   owner does not hold there, and restricting it to the personal tenant would lock out the very users
   the Fabric App serves.
2. **Cross-tenant guest access is already known to fail here.** Inviting the owner's own account across
   these tenants returned Entra error 530035, governed by cross-tenant and external-collaboration
   policy on the college side, which the owner does not control.
3. **The blast radius is credit, not data.** No Fabric token, no Gold row and no personal data passes
   through the Function. The budget alert caps the loss, and the credit expires 2026-12-14 regardless.

## Consequences

- The limitation is stated plainly in HONESTY.md rather than described as a security control.
- Abuse is deterred, not prevented: origin check, per-minute and per-day rate limits, size caps on the
  request and the reply, and a budget alert to the subscription owners.
- The public snapshot site does not wire the agent at all. It replays recorded, number-verified runs
  (`command_center/agent_runs.json`), so the endpoint is reachable only from the Fabric App's origin.
- **Revisit when** the project moves to a tenant the owner controls. Easy Auth is perhaps an hour's
  work there; it is the tenancy, not the feature, that blocks it.
- `docs/review/WAVE2_CHECKS.md` holds the longer investigation, including the Static Web Apps plan
  limits that rule out putting a login in front of the public page.
