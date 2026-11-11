SELECT event_name, COUNT(DISTINCT user_pseudo_id) AS users
FROM `proj.analytics.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20240101' AND '20240131'
GROUP BY event_name ORDER BY users DESC;
