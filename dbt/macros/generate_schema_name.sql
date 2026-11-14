{# Use the configured schema verbatim (gld), not <target_schema>_gld. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
