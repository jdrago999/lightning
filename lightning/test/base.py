from __future__ import absolute_import

import cyclone.httpclient
from twisted.enterprise import adbapi
from twisted.internet import defer, reactor
from twisted.test import proto_helpers
from twisted.trial import unittest
from twistar.registry import Registry

from lightning import Lightning
from lightning.model.authorization import Authz
from lightning.utils import compose_url

import json
import logging
import os
from pprint import pprint
import subprocess
from tempfile import NamedTemporaryFile
import time
from urllib import urlencode
from urlparse import urlparse, parse_qs
from twisted.internet.base import DelayedCall
#DelayedCall.debug = True

# This is passed into json.loads() to decode JSON arrays as sets and not lists.
def decode_list_as_set(dct):
    ret = {}
    for x in dct.keys():
        # Don't fix the error lists
        if type(dct[x]) == list and x != 'error':
            # This will not work for lists of dicts because dicts are not
            # hashable, thus cannot be elements of sets.
            try:
                ret[x] = set(dct[x])
            except:
                ret[x] = dct[x]
        else:
            ret[x] = dct[x]
    return ret

class TestWithRedis(object):
    """
    This is a mixin that allows for starting and stopping the redis server.
    """
    def start_redis(self):
        # Make sure the redis-server is actually dead, Jim. It needs to be very
        # very dead, Jim. Otherwise, it might be left over from a previous run.
        subprocess.call(
            ['killall', 'redis-server'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

        self.redis_port = 10000
        self.redis_conf_file = NamedTemporaryFile(delete=False)
        self.redis_conf_file.write("""
            daemonize no
            port %d
            timeout 10
            loglevel verbose
            logfile /tmp/redis_test.log
            databases 1
            dir /tmp/
        """ % (self.redis_port))
        self.redis_conf_file.close()
        self.redis_test_process = subprocess.Popen(['redis-server', self.redis_conf_file.name])
        time.sleep(0.1) # Needed to let the redis server get started
    def stop_redis(self):
        self.redis_test_process.terminate()
        self.redis_test_process.wait()
        os.unlink(self.redis_conf_file.name)


class TestWithSQL(object):
    """
    This is a mixin that allows for re-initializing our test SQL server.
    """

    @defer.inlineCallbacks
    def reset_db(self, db):
        project_path = os.path.normpath(
            os.path.dirname(__file__) + '../../..'
        )
        sql_table = subprocess.check_output([
            '%s/bin/generate_sql.py' % project_path,
            '--dbname=LIGHTNING_TEST',
            '--item=table',
        ])

        def make_table(txn, sql_table):
            txn.execute(sql_table)
            return True

        result = yield db.raw_db.runInteraction(make_table, sql_table)
        defer.returnValue(True)

class TestBase(unittest.TestCase):
    def assertURIEqual(self, gotten, expected):
        gotten_parse = urlparse(gotten)
        expected_parse = urlparse(expected)

        self.assertEqual( gotten_parse.scheme, expected_parse.scheme )
        self.assertEqual( gotten_parse.netloc, expected_parse.netloc )
        self.assertEqual( gotten_parse.path, expected_parse.path )
        self.assertEqual( gotten_parse.params, expected_parse.params )

        gotten_qs = parse_qs(gotten_parse.query)
        expected_qs = parse_qs(expected_parse.query)
        self.assertEqual( gotten_qs, expected_qs )

        self.assertEqual( gotten_parse.fragment, expected_parse.fragment )

    @defer.inlineCallbacks
    def assertNoAuthorization(self, client_name='testing', service_name='loopback', user_id='1234'):
        token_data = yield self.app.db.get_oauth_token(
            client_name=client_name, service_name=service_name,
            user_id=user_id,
        )
        self.assertEqual( len(token_data), 0, 'No oauth token' )

    @defer.inlineCallbacks
    def assertHasAuthorization(self, client_name='testing', service_name='loopback', user_id='1234'):
        token_data = yield self.app.db.get_oauth_token(
            client_name=client_name, service_name=service_name,
            user_id=user_id,
        )
        self.assertNotEqual( len(token_data), 0, 'Have oauth token' )


class TestLightning(TestBase, TestWithSQL, TestWithRedis):
    use_networking = True

    def setUp(self):
        logging.basicConfig(
            level='ERROR',
            format='[%(asctime)s] (%(levelname)s) %(module)s.%(funcName)s:%(lineno)d %(message)s',
            datefmt='%Y-%m-%d %I:%M:%S %p'
        )

        self.start_redis()
        self.config = {
            'sql_connection': 'dsn=SQLServer;uid=fakeuser;pwd=fakepassword;database=LIGHTNING_TEST;driver={SQL Server Native Client 10.0}',
            'environment': 'local',
            'redis_host': 'localhost',
            'redis_port': self.redis_port,
        }

        @defer.inlineCallbacks
        def on_build(app):
            self.app = app
            yield self.reset_db(app.db)
            if self.use_networking:
                self.listeners = [
                    reactor.listenTCP(0, self.app.site),
                ]


        # XXX - something goes wrong in the teardown process related to the redis connection pool
        # that we  can't figure out.  Fortunately, none of our tests actually need
        # to make use of that connection pool, so we added this do_connect_redis parameter to skip the
        # creation of the redis connection pool when running tests.
        return Lightning.build(self.config, do_connect_redis=False).addCallback(on_build)


    def tearDown(self):
        self.stop_redis()
        if self.use_networking:
            for listener in self.listeners:
                listener.stopListening()



    # Don't call this skip() - for some reason, that skips everything. Need to
    # investigate further later.
    def skip_me(self, msg=None):
        if not msg: msg = 'Skipping for no reason at all'
        raise unittest.SkipTest( msg )

    def getUrl(self, path='/'):
        if self.use_networking:
            port = self.listeners[0].getHost().port
        else:
            port = '0'
        return 'http://localhost:%s%s' % ( port, path )

    def fetch(self, path, list_as_set=False, **kwargs):
        if type(kwargs.get('postdata', None)) == dict:
            kwargs['postdata'] = urlencode(kwargs['postdata'], doseq=True)

        if self.use_networking:
            dResponse = cyclone.httpclient.fetch(
                url=self.getUrl(path=path), **kwargs
            )
        else:
            from cyclone.httpclient import Receiver
            from twisted.web._newclient import Request, Response
            from twisted.web.http_headers import Headers
            from twisted.test.proto_helpers import AccumulatingProtocol

            server_proto = self.app.buildProtocol( ('127.0.0.1', 0) )
            server_transport = proto_helpers.StringTransport()
            server_proto.makeConnection(server_transport)

            rawHeaders = kwargs.get('headers', {})
            rawHeaders['Host'] = ['localhost']
            req = Request(
                method=kwargs['method'],
                uri=path,
                headers=Headers( rawHeaders=rawHeaders ),
                bodyProducer=None,
            )
            req.writeTo(server_transport)
            server_proto.dataReceived(server_transport.value())
            print server_transport.value()

            # Strip out the original request.
            parts = server_transport.value().split("\r\n\r\n")
            actual_response = "\r\n\r\n".join(parts[1:])

            print actual_response

            from twisted.web._newclient import HTTPClientParser
            client_parser = HTTPClientParser(req, lambda x:x)
            client_parser.makeConnection(proto_helpers.StringTransport())
            client_parser.dataReceived(actual_response)
            response = client_parser.response

            # This was done in cyclone.httpclient
            if response.code in (204, 304):
                response.body = ''
                dResponse = defer.succeed(response)
            else:
                dResponse = defer.Deferred()
                response.deliverBody(Receiver(dResponse))
                def set_response(value):
                    response.body = value
                    return response
                dResponse.addCallback(set_response)

            # This triggers response.deliverBody. It needs a reason of some kind
            client_parser.connectionLost('Finished')

        if list_as_set:
            def decode_body(res):
                res.body = json.loads(res.body, object_hook=decode_list_as_set)
                return res
            dResponse.addCallback(decode_body)
        else:
            def decode_body(res):
                try:
                    res.body = json.loads(res.body)
                except:
                    print "counld not parse body: %s" % res.body
                return res
            dResponse.addCallback(decode_body)

        return dResponse

    def get(self, path, **kwargs):
        return self.fetch(method='GET', path=path, **kwargs)
    def post(self, path, **kwargs):
        if 'body' in kwargs:
            kwargs['postdata'] = kwargs['body']
        return self.fetch(method='POST', path=path, **kwargs)
    def put(self, path, **kwargs):
        if 'body' in kwargs:
            kwargs['postdata'] = kwargs['body']
        return self.fetch(method='PUT', path=path, **kwargs)
    def delete(self, path, **kwargs):
        return self.fetch(method='DELETE', path=path, **kwargs)

    @defer.inlineCallbacks
    def set_authorization(self, client_name='testing', service_name='loopback', user_id='a1234', token='asdf', **kwargs):
        assert user_id is not None
        assert token is not None

        self.authorization = yield Authz(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
            token=token,
            **kwargs
        ).set_token(self.app.db)
        self.uuid = self.authorization.uuid

    @defer.inlineCallbacks
    def expire_authorization(self, uuid=None, timestamp=None):
        refresh = not uuid
        if not uuid: uuid = self.uuid
        if not timestamp: timestamp = int(time.time())
        result = yield self.app.db.expire_oauth_token(
            uuid=uuid,
            timestamp=timestamp,
        )
        if refresh:
            yield self.set_authorization()

        defer.returnValue(result)




    def get_value(self, **kwargs):
        uuid = kwargs.get('uuid') or self.uuid
        authorization = kwargs.get('authorization') or self.authorization
        kargs = {
            'authorization': authorization,
            'method': kwargs['method'],
            'testcase': self,
        }

        d = self.app.db.get_value(**kargs)
        def on_return(ret):
            if len(ret):
                return(ret[0])
            return None
        d.addCallback(on_return)

        return d

    @defer.inlineCallbacks
    def get_value_range(self, **kwargs):
        assert kwargs.get('start') != None
        assert kwargs.get('end') != None
        kargs = {
            'authorization': kwargs.get('authoriztion', self.authorization),
            'start': kwargs['start'],
            'end': kwargs['end'],
            'method': kwargs['method'],
            'testcase': self,
        }
        rv = yield self.app.db.get_value_range(**kargs)
        defer.returnValue(rv)
    @defer.inlineCallbacks
    def write_value(self, uuid=None, **kwargs):
        assert 'method' in kwargs
        assert 'data' in kwargs
        if not uuid: uuid = self.uuid
        kargs = {
            'uuid': uuid,
            'timestamp': kwargs.get('timestamp', int(time.time())),
            'method': kwargs['method'],
            'data': kwargs['data'],
        }
        yield self.app.db.write_value(**kargs)

    def _x_and_verify(self, method, path, args, **kwargs):
        fetch_args = {
            x:kwargs[x]
            for x in [ 'headers', 'list_as_set' ]
            if kwargs.get(x)
        }
        if fetch_args.get('headers'):
            if not fetch_args['headers'].get('X-Client'):
                fetch_args['headers']['X-Client'] = [ 'testing' ]
        else:
            fetch_args['headers'] = {
                'X-Client': [ 'testing' ]
            }

        if method in [ 'GET', 'DELETE' ]:
            if args: path = compose_url(path, query=args)
            response = self.fetch(path=path, method=method, **fetch_args)
        elif method in [ 'POST', 'PUT' ]:
            if not args: args = ''
            response = self.fetch(
                path=path, method=method, postdata=args, **fetch_args
            )
        else:
            raise AttributeError(method)

        if kwargs.get('response_type'):
            def verify(response):
                if not isinstance(kwargs['response_type'], list):
                    kwargs['response_type'] = [kwargs['response_type']]

                self.assertEqual(response.headers['Content-Type'], kwargs['response_type'])
                return response
            response.addCallback(verify)
        if kwargs.get('response_location'):
            def verify(response):
                self.assertRegexpMatches(
                    response.headers.get('Location', [])[0], kwargs['response_location'],
                )
                return response
            response.addCallback(verify)

        if kwargs.get('result'):
            def verify(response):
                self.assertEqual(response.body,kwargs['result'])
                return response
            response.addCallback(verify)
        elif kwargs.get('result_matches'):
            def verify(response):
                self.assertRegexpMatches(response.body,kwargs['result_matches'])
                return response
            response.addCallback(verify)
        if kwargs.get('response_code'):
            def verify(response):
                self.assertEqual(response.code,kwargs['response_code'])
                return response
            response.addCallback(verify)

        return response

    def get_and_verify(self, path, args=None, **kwargs):
        return self._x_and_verify('GET', path, args, **kwargs)
    def post_and_verify(self, path, args=None, **kwargs):
        return self._x_and_verify('POST', path, args, **kwargs)
    def put_and_verify(self, path, args=None, **kwargs):
        return self._x_and_verify('PUT', path, args, **kwargs)
    def delete_and_verify(self, path, args=None, **kwargs):
        return self._x_and_verify('DELETE', path, args, **kwargs)
