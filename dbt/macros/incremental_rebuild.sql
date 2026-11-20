{#
    Incremental Gold: the watermark, and the one rule that makes it safe (ADR-015).

    Three Gold facts are built incrementally. All three use the SAME shape, and these two macros are that
    shape, written once so a model cannot quietly get it wrong:

      1. `since_last_arrival()` gives the cut-off: the newest source arrival already reflected in the table.
      2. The model finds the KEYS touched by anything that arrived at or after that cut-off, and then
         REBUILDS THOSE KEYS IN FULL from all of Silver -- not just the new rows.

    Step 2 is the whole thing, and the reason "incremental" is not the same as "append". A day's
    reconciliation is a sum over every payment, bank line and GL line for that day. If a late bank file
    arrives for a day already in Gold and we appended only the new line, the day would hold two partial
    rows and the variance would be nonsense. Deleting the day and re-deriving it from the full Silver
    history gives byte-identical output to a full rebuild, which is what tests/test_gold_incremental.py
    asserts by running both and diffing them.

    WHY `>=` AND NOT `>`.
    Bronze stamps every row in one landing batch with the same `current_timestamp()`. If the cut-off were
    exclusive, a row that shares its timestamp with the recorded maximum would be skipped forever. With
    `>=` the last batch is simply processed again. Because the rebuild is a full re-derivation of whole
    keys, doing it twice changes nothing -- so the cost of `>=` is a little repeated work and the cost of
    `>` is silent data loss. That is not a close call.

    WHAT THIS DOES NOT CATCH, and when to run `dbt build --full-refresh` instead:
      * a change to reference data (the acquirer fee schedule, the GL account role map, the dbt vars that
        set the dispute thresholds). Nothing in Bronze arrives, so no watermark moves, and Gold keeps the
        figures it already has. docs/RUNBOOKS.md lists this under re-running and backfilling.
      * an edit to a model's own SQL. dbt does not know the logic changed.
    Both are handled the same way and the full refresh is cheap here; the point is that it is a decision
    somebody makes, not something the schedule does by accident.

    WHAT IT ASSUMES: that Bronze is landed by one writer at a time, so arrival timestamps never go
    backwards. That is true of this pipeline -- the Airflow DAG runs bronze_land as a single task and the
    chain is linear. Two concurrent landings could interleave timestamps and a row could land "before" a
    watermark already recorded. If Bronze ever becomes concurrent, this must become a stored watermark in
    ctl.ingestion_watermarks rather than a MAX() over Gold.
#}

{% macro since_last_arrival() %}
    {#- The cut-off, as a scalar sub-query. The COALESCE floor matters: on a table that exists but is
        empty, MAX() is NULL and every `>=` comparison would be NULL, i.e. false, so the model would
        select nothing at all and the table would stay empty for good. -#}
    (SELECT COALESCE(MAX(last_source_arrival_at), CAST('1900-01-01' AS {{ dbt.type_timestamp() }}))
     FROM {{ this }})
{% endmacro %}


{% macro arrival_floor() %}
    {#- Used in the non-incremental (full build) branch so the column has the same type on both paths. -#}
    CAST('1900-01-01' AS {{ dbt.type_timestamp() }})
{% endmacro %}
