/*
    Setup the changescript table and stored procedure to record changescripts
*/
USE [$(database)]
GO

SET ANSI_NULLS ON
GO  

SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[ChangeScript](
    [ChangeScript] [int] IDENTITY(1,1) NOT NULL,
    [TSLastModified] [timestamp] NOT NULL,
    [Name] [nvarchar](1024) NOT NULL,
    [Notes] [nvarchar](1024) NULL,
    [DateRun] [datetime] NULL,
PRIMARY KEY CLUSTERED 
(
    [ChangeScript] ASC
)WITH (PAD_INDEX  = OFF, STATISTICS_NORECOMPUTE  = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS  = ON, ALLOW_PAGE_LOCKS  = ON) ON [PRIMARY]
) ON [PRIMARY]

GO

ALTER TABLE [dbo].[ChangeScript] ADD  CONSTRAINT [DF_ChangeScript_DateRun]  DEFAULT (getdate()) FOR [DateRun]
GO

/*
    Inserts or updates record in the ChangeScript administrative table.
*/
CREATE PROCEDURE [dbo].[usp_RecordChangeScript]
    @scriptname nvarchar(1024),
    @notes      nvarchar(1024) = NULL
AS BEGIN
    IF NOT EXISTS (SELECT [Name] FROM ChangeScript WHERE [Name] = @scriptname)
        INSERT INTO ChangeScript ([Name], Notes) VALUES (@scriptname, @notes)
    ELSE
        UPDATE ChangeScript
        SET DateRun = getdate()
        WHERE [Name] = @scriptname

    IF @notes IS NOT NULL
        UPDATE ChangeScript
        SET Notes = @notes
        WHERE [Name] = @scriptname
END

GO