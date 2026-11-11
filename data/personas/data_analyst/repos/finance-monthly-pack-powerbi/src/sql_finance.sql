WITH monthly AS (
    SELECT date_trunc('month', created_at) AS m, customer_id, SUM(amount) AS spend
    FROM orders GROUP BY 1, 2
)
SELECT m, COUNT(*) AS buyers, AVG(spend) AS avg_spend,
       SUM(spend) OVER (ORDER BY m) AS running_total
FROM monthly GROUP BY m ORDER BY m;
