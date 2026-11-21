-- Line-level reconciliation: the leg the merchant-day model cannot have (closes HONESTY row 19's blind spot).
--
-- `fact_merchant_settlement_recon` reconciles at merchant x day, which is the right grain for the question
-- it answers and carries one arithmetic consequence: two errors that offset inside the same GROUP BY cancel.
-- +5.00 SAR on one capture and -5.00 on another, same merchant, same day, and the day still reads SAR 0.00.
-- That is not a bug in the SQL -- no sum over a day can see it -- and five reviewers raised it, correctly, as
-- the one criticism of "variance 0.00" that cannot be argued away.
--
-- Catching it needs a join on `payment_event_id`, which is exactly what this is. One bank line per payment
-- event is a stated contract (slv.settlement_lines, `unique` on payment_event_id), so the amount the bank
-- settled must equal the amount the till captured, line by line, with no summing anywhere.
--
-- **That contract is this project's, not every acquirer's -- check before reusing this rule.** Real
-- settlement files split a single capture across batches, net several captures into one line, or settle
-- partially; against a file like that this test would fail on correct data, which is worse than not having
-- it. The fix there is a matching leg that groups the bank side by payment_event_id before comparing, and
-- it needs the actual file format in hand to write. Raised by external review on 2026-11-21, HONESTY row 19.
--
-- QUARANTINED lines are excluded because a mismatch is precisely why they are quarantined: that finding is
-- already recorded in quarantine.settlement_breaks and re-reporting it here would turn a working control
-- into a permanently red test.
--
-- **Why this is an independent check and not a restatement.** Silver computes `settlement_status` at build
-- time by comparing these same two amounts. This runs at Gold build time against whatever the tables now
-- hold, so it does not trust that earlier comparison -- which is the whole point of an independent
-- reconciliation leg. If a payment amount is changed after Silver was built, the line keeps its PAID_BANK
-- status and this test is the thing that notices.
SELECT p.payment_event_id,
       p.merchant_id,
       p.business_date_ksa,
       p.amount_sar       AS captured_sar,
       s.gross_amount_sar AS settled_sar
FROM {{ source('slv_lakehouse', 'payment_lifecycle') }} p
JOIN {{ source('slv_lakehouse', 'settlement_lines') }} s
  ON s.payment_event_id = p.payment_event_id
WHERE s.settlement_status <> 'QUARANTINED'
  AND p.amount_sar <> s.gross_amount_sar
