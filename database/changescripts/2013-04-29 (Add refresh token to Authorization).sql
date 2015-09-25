USE [Lightning]

ALTER TABLE [dbo].[InflightAuthorization] DROP COLUMN [request_token];
ALTER TABLE [dbo].[InflightAuthorization] DROP COLUMN [secret];
ALTER TABLE [dbo].[InflightAuthorization] ADD [request_token] [nvarchar](max) DEFAULT NULL;
ALTER TABLE [dbo].[InflightAuthorization] ADD [secret] [nvarchar](max) DEFAULT NULL;

ALTER TABLE [dbo].[InflightAuthorization] ADD [state] [nvarchar](max) DEFAULT NULL;
ALTER TABLE [dbo].[Authorization] ADD [refresh_token] [nvarchar](max) DEFAULT NULL;
ALTER TABLE [dbo].[Authorization] ADD [redirect_uri] [nvarchar](max) DEFAULT NULL;