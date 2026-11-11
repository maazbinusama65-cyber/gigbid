# Analytics Warehouse with dbt

**Client industry:** SaaS  
**Completed:** 2024-01  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: every team had its own definition of active customer. They described what they wanted as a tidy reporting tables.

## What I built

Under the hood: dbt.
I used Snowflake for this part.
Under the hood: SQL.
A key piece was fact and dimension tables arranged for easy slicing.
I set up a nightly DAG that reruns safely when a step fails.

## Outcome

Result: 42 tested models; metric disputes in leadership meetings went away.

## A snippet

```sql
{{ config(materialized='incremental', unique_key='order_id') }}
SELECT order_id, customer_id, ordered_at, net_amount
FROM {{ ref('stg_orders') }}
{% if is_incremental() %}WHERE ordered_at > (SELECT MAX(ordered_at) FROM {{ this }}){% endif %}
```

