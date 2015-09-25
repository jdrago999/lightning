#!/usr/bin/env python

import os
import sys
sys.path.append(os.path.dirname(__file__) + '/..')

from twistedpyres import ResQ
from twisted.internet import reactor

d = ResQ.connect()

if False:
    from lightning.service.loopback import LoopbackDaemon
    def enqueue(resq):
        return resq.enqueue(LoopbackDaemon, {
            'redis':{
                'host': 'localhost',
                'port': 6379,
            },
            'environment': 'local',
        }, 'token_1234')
    d.addCallback(enqueue)
else:
    from lightning.service.facebook import FacebookDaemon
    from lightning.service.instagram import InstagramDaemon
    from lightning.service.twitter import TwitterDaemon
    from lightning.service.loopback import LoopbackDaemon
    def enqueue(resq):
        return resq.enqueue(FacebookDaemon, {
            'sql':{
                'connection':'dsn=SQLServer;uid=fakeuser;pwd=fakepassword;database=LIGHTNING;driver={SQL Server Native Client 10.0}',
            },
            'environment': 'local',
        #}, '50a5ed20-a4c6-43b4-ac8d-3256c0381e48') # Instagram
        }, '99be42f7-3cca-4e36-9f4d-0d3510694d56') # Facebook
        #}, 'e1921fe1-f14f-44a0-86c8-31f2905b3d75') # Twitter
    d.addCallback(enqueue)

def stop_reactor(err):
    if err: print "Stopping because of ", err
    reactor.stop()
d.addBoth(stop_reactor)

reactor.run()
