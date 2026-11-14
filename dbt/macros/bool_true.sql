{# Lakehouse booleans arrive as BOOLEAN in DuckDB and as BIT through the Fabric SQL endpoint. #}
{% macro bool_true() -%}
    {{ return('1' if target.type == 'fabric' else 'TRUE') }}
{%- endmacro %}
