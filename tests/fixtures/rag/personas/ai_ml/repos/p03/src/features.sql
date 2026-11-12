CREATE TABLE churn_features AS
SELECT customer_id, AVG(minutes_used) AS avg_minutes, COUNT(support_calls) AS calls
FROM usage_events GROUP BY customer_id;
