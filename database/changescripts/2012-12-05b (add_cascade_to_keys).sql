USE $(database)

SET ANSI_NULLS ON
SET QUOTED_IDENTIFIER ON

IF  EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[UserData]') AND type in (N'U'))
DROP TABLE [dbo].[UserData]
IF  EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[GranularData]') AND type in (N'U'))
DROP TABLE [dbo].[GranularData]
CREATE TABLE [dbo].[UserData](
        [uuid] [nchar](36) NOT NULL,
        [method] [nvarchar](100) NOT NULL,
        [timestamp] [bigint] NOT NULL,
        [data] [nvarchar](max) NULL
    ) ON [PRIMARY]

ALTER TABLE [dbo].[UserData]
    ADD CONSTRAINT UX_UserData_uuid_method_ts UNIQUE(uuid, method, timestamp)
ALTER TABLE [dbo].[UserData]
    ADD CONSTRAINT FK_UserData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE

CREATE TABLE [dbo].[GranularData](
    [uuid] [nchar](36) NOT NULL,
    [method] [nvarchar](100) NOT NULL,
    [item_id] [nvarchar](100) NOT NULL,
    [actor_id] [nvarchar](100) NOT NULL,
    [timestamp] [bigint] NOT NULL
) ON [PRIMARY]

ALTER TABLE [dbo].[GranularData]
    ADD CONSTRAINT PK_GranularData PRIMARY KEY (uuid, method, item_id)

ALTER TABLE [dbo].[GranularData]
    ADD CONSTRAINT FK_GranularData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
