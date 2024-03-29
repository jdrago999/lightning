USE [LIGHTNING]
GO

/****** Object:  Index [IX_UserData_timestamp]    Script Date: 08/13/2013 09:11:46 ******/
CREATE NONCLUSTERED INDEX [IX_UserData_timestamp] ON [dbo].[UserData] 
(
	[timestamp] ASC
)WITH (PAD_INDEX  = OFF, STATISTICS_NORECOMPUTE  = OFF, SORT_IN_TEMPDB = OFF, IGNORE_DUP_KEY = OFF, DROP_EXISTING = OFF, ONLINE = OFF, ALLOW_ROW_LOCKS  = ON, ALLOW_PAGE_LOCKS  = ON) ON [PRIMARY]
GO



