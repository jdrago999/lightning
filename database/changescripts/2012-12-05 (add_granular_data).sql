USE $(database)

SET ANSI_NULLS ON
SET QUOTED_IDENTIFIER ON

IF  EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[GranularData]') AND type in (N'U'))
DROP TABLE [dbo].[GranularData]

CREATE TABLE [dbo].[GranularData](
    [uuid] [nchar](36) NOT NULL FOREIGN KEY REFERENCES [Authorization] (uuid),
    [method] [nvarchar](100) NOT NULL,
    [item_id] [nvarchar](100) NOT NULL,
    [actor_id] [nvarchar](100) NOT NULL,
    [timestamp] [bigint] NOT NULL
) ON [PRIMARY]

ALTER TABLE [dbo].[GranularData]
    ADD CONSTRAINT PK_GranularData PRIMARY KEY (uuid, method, item_id)
