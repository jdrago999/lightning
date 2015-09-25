USE [Lightning]

UPDATE [Authorization]
SET refresh_token = secret, secret = NULL
WHERE service_name in ('googleplus', 'blogger', 'youtube') AND refresh_token IS NULL AND secret IS NOT NULL