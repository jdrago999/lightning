USE [Lightning]
update 
	ud 
set 
	method = 'num_media' 
from 
	UserData ud 
	inner join [Authorization] a 
		on ud.uuid = a.uuid
where 
	ud.method = 'num_photos' 
	and [a].[service_name] = 'instagram'
	
