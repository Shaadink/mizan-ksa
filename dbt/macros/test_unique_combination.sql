{# Generic test: the combination of columns is unique (the declared grain). #}
{% test unique_combination(model, columns) %}
    SELECT {{ columns | join(', ') }}, COUNT(*) AS n
    FROM {{ model }}
    GROUP BY {{ columns | join(', ') }}
    HAVING COUNT(*) > 1
{% endtest %}
