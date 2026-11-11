SELECT date_trunc('month', first_order) AS cohort,
       date_part('month', age(o.created_at, first_order)) AS month_n,
       COUNT(DISTINCT o.customer_id) AS active
FROM orders o JOIN firsts f USING (customer_id)
GROUP BY 1, 2 ORDER BY 1, 2;
