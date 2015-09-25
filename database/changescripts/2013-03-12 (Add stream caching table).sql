USE $(database)

SET ANSI_NULLS ON
SET QUOTED_IDENTIFIER ON

IF  EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[StreamCache]') AND type in (N'U'))
DROP TABLE [dbo].[StreamCache]

CREATE TABLE [dbo].[StreamCache](
    [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [uuid] [nchar](36) NOT NULL FOREIGN KEY REFERENCES [Authorization] (uuid),
    [item_id] [nvarchar](100) NOT NULL,
    [timestamp] [bigint] NOT NULL,
    [data] [text] NOT NULL
) ON [PRIMARY]

ALTER TABLE [dbo].[StreamCache]
    ADD CONSTRAINT FK_StreamCache_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
