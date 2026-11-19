{# Days between two dates on both targets. DuckDB wants the part quoted, T-SQL wants it bare, so a model
   that writes either one directly builds on one target and fails on the other -- which is how
   fact_merchant_dispute_monitor first failed on Fabric with "'DATE_DIFF' is not a recognized built-in
   function name". Same reason as bool_true(). #}
{% macro date_diff_days(start_date, end_date) -%}
    {%- if target.type == 'fabric' -%}
        DATEDIFF(day, {{ start_date }}, {{ end_date }})
    {%- else -%}
        DATE_DIFF('day', {{ start_date }}, {{ end_date }})
    {%- endif -%}
{%- endmacro %}
