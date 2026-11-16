# Wave 2 feasibility checks (2026-11-16)

Two Wave 2 items were checks rather than features: find out whether they are possible here, and record
the answer so nobody re-investigates. Both answers are **no, not on this setup**, for concrete reasons.

---

## 1. Activator alerts ("tell me when money does not reconcile")

**Verdict: do not build it on this capacity.**

**What it would be.** A Fabric Activator rule watching `gld.fact_merchant_settlement_recon`, firing when
unexplained bank or GL variance leaves 0.00, or when a simplified invoice misses the 24-hour reporting
window. Conceptually a good fit: MIZAN already computes both conditions.

**Why not here.**

| Blocker | Detail |
|---|---|
| Trial capacity | The workspace runs on `Fabric trial FTL64` in a college tenant. The trial ends after 60 days and the college can disable it at any time. |
| Rules outlive the trial | Alerts created on a trial capacity keep firing after it expires and cannot be edited or disabled, because the items become inaccessible without a licence. An alert nobody can turn off is worse than no alert. |
| Not the owner's tenant | The capacity belongs to the college, not to the project owner, so there is no way to guarantee the rule's lifetime or to clean it up later. |

**What we do instead.** The same two conditions are already enforced where they matter, and they *block*
rather than notify: the dbt circuit breaker fails the build when variance is not 0.00 (see the chaos bar's
"Break reconciliation"), and the KQL rules in Eventhouse detect late ZATCA reporting on the replayed
stream. A notification is weaker than a build that refuses to publish.

**Revisit if** the project moves to a paid F2+ capacity in an owned tenant. The rule itself is perhaps an
hour of work; it is the capacity, not the feature, that blocks it.

---

## 2. Easy Auth on the public page ("make the public URL require a login")

**Verdict: not worth it, and it would not do what it needs to do.**

**What it would be.** Microsoft Entra sign-in in front of
`delightful-field-01a948c0f.4.azurestaticapps.net`, so the public snapshot is visible only to invited
people rather than to anyone with the link.

**Why not.**

| Blocker | Detail |
|---|---|
| The free tier cannot restrict a tenant | Static Web Apps' built-in Entra provider accepts **any** Microsoft account, so it is a sign-in prompt, not an access control. Restricting to specific people needs a *custom* Entra provider. |
| Custom providers are a paid feature | Custom authentication requires the Static Web Apps **Standard** plan. The site is on Free, which is why it costs nothing today. |
| Cross-tenant guests are already a known problem | This project hit Entra error **530035** earlier when inviting the owner's own Gmail account into the Azure tenant. Guest access is governed by cross-tenant and external-collaboration policy, which the owner does not control on the college side. |
| It defeats the purpose | The public page exists precisely because the Fabric App is locked behind a college tenant that recruiters cannot enter. Putting a login back in front of it recreates the problem it was built to solve. |

**What we do instead.** Keep the page public and keep it safe by construction:
`scripts/build_public_site.py` refuses to publish if the page contains an e-mail address, the Azure
Function endpoint, a tenant domain, or anything shaped like a secret. The data is synthetic throughout,
and the live agent is not wired into the public copy (it replays recorded, number-verified runs).

**Revisit if** the page ever needs to show something that is not synthetic. At that point the honest
answer is a paid Standard plan with a custom Entra provider, not a shared link.

---

## Sources

- [Fabric Activator overview](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/data-activator/activator-introduction)
- [Fabric trial capacity](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial)
- [Static Web Apps: authentication and authorization](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-authorization)
- [Static Web Apps: custom authentication](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-custom)
- [Entra cross-tenant access settings](https://techcommunity.microsoft.com/blog/microsoft-entra-blog/cross-tenant-access-settings---notes-from-the-field/4081841)
