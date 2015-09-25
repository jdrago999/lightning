use LIGHTNING
update UserData set data = str(cast(cast(data as float) * 0.62 / 1000 as float))
where method = 'total_distance'
