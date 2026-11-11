{{ config(materialized='incremental', unique_key='order_id') }}
SELECT order_id, customer_id, ordered_at, net_amount
FROM {{ ref('stg_orders') }}
{% if is_incremental() %}WHERE ordered_at > (SELECT MAX(ordered_at) FROM {{ this }}){% endif %}
