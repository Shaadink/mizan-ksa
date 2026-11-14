{# One row per calendar day in [start_date, end_date). Dialect-specific series, same output. #}
{% macro date_spine(start_date, end_date) -%}
    {{ return(adapter.dispatch('date_spine', 'mizan_ksa')(start_date, end_date)) }}
{%- endmacro %}

{% macro duckdb__date_spine(start_date, end_date) -%}
    SELECT CAST(range AS DATE) AS calendar_date
    FROM range(DATE '{{ start_date }}', DATE '{{ end_date }}', INTERVAL 1 DAY)
{%- endmacro %}

{% macro fabric__date_spine(start_date, end_date) -%}
    SELECT DATEADD(day, value, CAST('{{ start_date }}' AS DATE)) AS calendar_date
    FROM GENERATE_SERIES(0, DATEDIFF(day, CAST('{{ start_date }}' AS DATE), CAST('{{ end_date }}' AS DATE)) - 1)
{%- endmacro %}
