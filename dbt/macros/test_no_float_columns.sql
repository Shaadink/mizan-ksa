{# Generic test (I-06): a financial model must not expose FLOAT/DOUBLE/REAL columns. #}
{% test no_float_columns(model) %}
    {% set cols = adapter.get_columns_in_relation(model) %}
    {% set bad = [] %}
    {% for c in cols %}
        {% if c.dtype | lower in ('float', 'double', 'real', 'float4', 'float8', 'double precision') %}
            {% do bad.append(c.name) %}
        {% endif %}
    {% endfor %}
    SELECT '{{ bad | join(",") }}' AS float_columns WHERE 1 = {{ 1 if bad else 0 }}
{% endtest %}
