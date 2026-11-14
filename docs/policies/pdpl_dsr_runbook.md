---
doc_id: POL-PDPL-003
title: PDPL data-subject erasure runbook
classification: CONFIDENTIAL
acl_groups: DPO, PRIVACY_OPS
---
# Intake
A data-subject request is verified by the DPO. The person is resolved through the National ID or the source
customer reference to every linked record before any action.

# Execution
Run execute_dsr. Keys are shredded and the vault is vacuumed. Signed tax invoices stay under legal hold as
LEGAL_HOLD_RETAINED. Evidence is written to audit.pdpl_dsr_evidence.

# Restore guard [SECRET]
After any backup restore, run restore_guard before serving any table. Escalation contacts for a failed guard are
held by the security team only.
