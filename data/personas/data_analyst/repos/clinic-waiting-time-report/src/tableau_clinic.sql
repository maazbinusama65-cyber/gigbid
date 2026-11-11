-- custom SQL behind the workbook
SELECT region, store_id, DATE_TRUNC('week', sold_at) AS week, SUM(net_amount) AS revenue
FROM sales WHERE sold_at >= CURRENT_DATE - INTERVAL '26 weeks'
GROUP BY 1, 2, 3;
