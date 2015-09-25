from __future__ import absolute_import
import tornadoredis


class Datastore(object):
    "The datastore for the Lightning console"
    def __init__(self, address='localhost:6379', database=2):
        (host, port) = address.split(':')
        self.redis = tornadoredis.Client(host, int(port))
        self.redis.connect()
        self.redis.select(database)
