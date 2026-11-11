SELECT metric, actual, target, CASE WHEN actual >= target THEN 'green' WHEN actual >= 0.9 * target THEN 'amber' ELSE 'red' END AS status
FROM weekly_kpis WHERE week = (SELECT MAX(week) FROM weekly_kpis);
