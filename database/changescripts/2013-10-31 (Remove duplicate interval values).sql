USE [Lightning]

DELETE FROM [UserData]
WHERE uuid IN (SELECT DISTINCT uuid FROM [UserData] GROUP BY uuid, method, data having COUNT(data) > 1)
AND method IN (SELECT DISTINCT method FROM [UserData] GROUP BY uuid, method, data having COUNT(data) > 1)