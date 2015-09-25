-- This Script should be run with the 

USE [LIGHTNING]
GO

alter table [Authorization] add expired_on_timestamp bigint
GO

update a 
set a.expired_on_timestamp = ea.[timestamp] 
from  [Authorization] as a 
inner join ExpiredAuthorization as ea
on a.uuid = ea.uuid
GO

drop table ExpiredAuthorization
