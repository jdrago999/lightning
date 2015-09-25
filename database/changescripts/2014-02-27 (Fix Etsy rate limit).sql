USE [LIGHTNING]

IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Limit]') AND type in (N'U'))
    DROP TABLE [dbo].[Limit]

CREATE TABLE [dbo].[Limit](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL FOREIGN KEY REFERENCES [Authorization] (uuid),
        [last_called_on] [bigint] NOT NULL
    ) ON [PRIMARY]

ALTER TABLE [dbo].[Limit]
    ADD CONSTRAINT FK_Limit_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
