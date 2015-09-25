"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    Service, Web, Daemon, recurring, daemon_class, service_class, api_method,
    Profile
)
from lightning.model.authorization import Authz

from twisted.web.error import Error
from twisted.internet import defer

from calendar import timegm
from datetime import timedelta
import faker
import iso8601
import random
import time


class Loopback(Service):
    "Base Loopback serive definition"
    name='loopback'
    def __init__(self, *args, **kwargs):
        super(Loopback, self).__init__(*args, **kwargs)
        self.oauth_token = 'token_1234'

    ############################################
    # Below is the list of functions required to support reading the feed

    def get_feed_url(self, **kwargs):
        'The feed URL'
        return '/me/feed'
    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return { 'limit': limit }
    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        timestamp = kwargs.get('timestamp', int(time.time()))
        if kwargs.get('forward', False):
            return { 'since': timestamp }
        else:
            return { 'until': timestamp }
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        return dict(
            post_id=post['id'],
            timestamp=timegm(
                iso8601.parse_date(post['created_time']).timetuple()
            ),
            user_id=post.get('from', {}).get('id', ''),
            user_name=post.get('from', {}).get('name', ''),
            text=post.get('story', ''),
        )

    # TO HERE
    ############################################

@daemon_class
class LoopbackDaemon(Loopback, Daemon):
    """
    This is the Daemon half for the loopback service. It implements the data
    collection piece for the Loopback service.
    """

    _delay = timedelta(seconds=1)
    def serialize_value(self, method, value):
        'Overridden method to determine how to serialize the values returned'
        if method == 'other_profile':
            return value
        elif method in ['random', 'ten']:
            return value['num']
        else:
            return value['data']

    @recurring
    def fortytwo(self, **kwargs):
        'Returns the string "fortytwo"'
        return defer.succeed({
            'data': 'fortytwo',
        })

    @recurring
    def ten(self, **kwargs):
        'Returns the number 10'
        return defer.succeed({
            'num': 10,
        })
        # This version will wait two seconds before finishing. It's useful for
        # testing how twistedpyres behaves.
        #from twisted.internet import task, reactor
        #def foo():
        #    return { 'num': 10 }
        #return task.deferLater(reactor, 2, foo)

    @recurring
    def random(self, **kwargs):
        'Returns a random number between 1 and 999,999'
        return defer.succeed({
            'num': str(random.randint(1, 999999)),
        })

    @recurring
    def time(self, **kwargs):
        'Returns the current time in seconds since epoch'
        print 'trying to get time'
        return defer.succeed({
            'data': str(int(time.time())),
        })

    @recurring
    def other_profile(self, **kwargs):
        "Returns a random profile"
        first_name = faker.name.name()
        last_name = faker.name.name()
        name = first_name + ' ' + last_name
        email = faker.internet.email()
        return defer.succeed(
            Profile(
                email=email,
                name=name,
            )
        )

class LoopbackWebBase(Loopback):
    "This is the baseclass for all the Loopback Web services."
    def start_authorization(self, **kwargs):
        """
        The entry point for starting authorization.

        This method will return the redirect_uri provided by the client, plus
        some useful parameters, and any permissions the client has requested.

        The useful parameters will be used to create tokens and users when the
        client returns back to finish_authorization().

        Unlike all other authorizations, the username parameter is required so
        that no-one has to build a third-party service mock. This username
        parameter is used in finish_authorization() to potentially find the
        user and return an existing authorization UUID.
        """
        self.ensure_arguments(
            ['redirect_uri', 'username'],
            kwargs.get('args', {}),
        )
        return defer.succeed(
            self.construct_authorization_url(
                base_uri=kwargs['args']['redirect_uri'], **kwargs
            )
        )

    def finish_authorization(self, client_name, **kwargs):
        """
        The entry point for finishing authorization. This assumes that it was
        called using the parameters that start_authorization() provided, plus
        the original redirect_uri as passed into start_authorization().
        """
        self.ensure_arguments(
            ['redirect_uri', 'username'],
            kwargs.get('args', {}),
        )
        authorization = Authz(
            client_name=client_name,
            service_name=self.name,
            token=self.oauth_token,
            user_id=kwargs['args']['username'],
        )
        d = authorization.set_token(self.datastore)
        def return_authz(_):
            return authorization
        d.addCallback(return_authz)
        return d

    def revoke_authorization(self, authorization):
        "The entry point for revoking authorization"
        return defer.succeed( True )

@service_class
class LoopbackWeb(LoopbackWebBase, Web):
    name='loopback'
    permissions = {
        'testing2': {
            'scope': 'email,name',
        },
    }
    daemon_class = LoopbackDaemon

    # These are web-only methods
    @api_method('GET')
    def broken(self, **kwargs):
        'Returns a 500 error'
        raise Error(500, "This method is intentionally broken")

    @api_method('GET')
    def sleep(self, **kwargs):
        'Sleeps for the time in the "data" string (default 0.1s)'
        sleeptime = float(kwargs.get('arguments', dict()).get('data', '0.1'))
        time.sleep(sleeptime)
        return defer.succeed({
            'data': str(sleeptime),
        })

    @api_method('GET')
    def whoami(self, **kwargs):
        'Returns the client name in the "data" string'
        assert kwargs.get('authorization') != None
        return defer.succeed({
            'data': kwargs['authorization'].client_name,
        })

    @api_method('GET')
    def profile(self, **kwargs):
        """Returns a random profile"""
        assert kwargs.get('authorization') != None
        first_name = faker.name.name()
        last_name = faker.name.name()
        name = first_name + ' ' + last_name
        email = faker.internet.email()
        defer.returnValue(
            Profile(
                email=email,
                name=name,
            )
        )

    @api_method('POST')
    def sleep_post(self, **kwargs):
        'Sleeps for the time in the "data" string (default 0.1s)'
        sleeptime = float(kwargs.get('arguments', dict()).get('data', '0.1'))
        time.sleep(sleeptime)
        return defer.succeed({
            'data': str(sleeptime),
        })

LoopbackWeb.api_method(
    'fortytwo', 'data',
    present='Returns the string "fortytwo"',
    interval='Returns the string "fortytwo" over time',
)
LoopbackWeb.api_method(
    'ten', 'num',
    present='Returns the string "10"',
    interval='Returns the string "10" over time',
)
LoopbackWeb.api_method(
    'time', 'data',
    present='Returns the current time in seconds since epoch',
    interval='Returns the current time in seconds since epoch over time',
)
LoopbackWeb.api_method(
    'random', 'num',
    present='Returns a random number between 1 and 999,999',
    interval='Returns a series of random numbers between 1 and 999,999',
)
LoopbackWeb.api_method(
    'other_profile',
    present='Returns a random profile',
)
# These are methods added to test the feed and /stream
LoopbackWeb.api_method(
    'num_foo', 'num',
    present='Number of foos',
    interval='Number of foos over time',
)

class Loopback2Daemon(Loopback, Daemon):
    pass

@service_class
class Loopback2Web(LoopbackWebBase, Web):
    """
    This is the Web side of another service. It doesn't have a Daemon side.
    """
    name = 'loopback2'
    daemon_class = Loopback2Daemon
    @api_method('GET')
    def time(self, **kwargs):
        'Returns the current time in seconds since epoch'
        return defer.succeed({
            'data': str(int(time.time())),
        })

# These are methods added to test the feed and /stream
Loopback2Web.api_method(
    'num_foo', 'num',
    present='Number of foos',
    interval='Number of foos over time',
)

