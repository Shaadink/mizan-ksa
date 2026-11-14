-- One row per ACTIVE golden party profile (current SCD2 version). No PII: names stay encrypted in Silver;
-- Gold carries the golden key, the anchor TYPE (never the value), membership size and the current SPL region.
WITH g AS (
    SELECT golden_id, version, party_type, anchor_id_type, member_count, city, valid_from
    FROM {{ source('slv_lakehouse', 'golden_party_scd2') }}
    WHERE is_current = {{ bool_true() }} AND status = 'ACTIVE'
),
a AS (
    SELECT golden_id, region_letter, district, city AS address_city, observed_date AS address_observed_date
    FROM {{ source('slv_lakehouse', 'address_observations') }}
    WHERE is_current_for_golden = {{ bool_true() }}
)
SELECT g.golden_id,
       CAST(g.version AS INT)                                         AS scd2_version,
       g.party_type,
       COALESCE(g.anchor_id_type, 'NONE')                             AS anchor_id_type,
       CASE WHEN g.anchor_id_type IS NULL THEN 0 ELSE 1 END           AS has_verified_anchor,
       CAST(g.member_count AS INT)                                    AS member_count,
       g.city,
       a.region_letter, a.district, a.address_city, a.address_observed_date,
       g.valid_from
FROM g
LEFT JOIN a ON a.golden_id = g.golden_id
