USE $(database)

SET ANSI_NULLS ON
SET QUOTED_IDENTIFIER ON

DECLARE @sqlForeignKeys VARCHAR(MAX)
SELECT @sqlForeignKeys = ISNULL(@sqlForeignKeys,'') +
'ALTER TABLE dbo.[' + OBJECT_NAME(FK.parent_object_id) + '] DROP CONSTRAINT [' + FK.name + '];' + CHAR(10)
FROM SYS.FOREIGN_KEYS FK
EXEC(@sqlForeignKeys)

ALTER TABLE [dbo].[ExpiredAuthorization]
    ADD CONSTRAINT FK_ExpiredAuthorization_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
ALTER TABLE [dbo].[GranularData]
    ADD CONSTRAINT FK_GranularData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
ALTER TABLE [dbo].[UserData]
    ADD CONSTRAINT FK_UserData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE
