from __future__ import absolute_import

from .base import TestHandler
from lightning.error import error_format
from twisted.internet import defer


class TestApiHandler(TestHandler):
    def test_get(self):
        return self.get_and_verify(
            path='/api',
            response_code=200,
            list_as_set=True,
            result={'services': set([
                'loopback',
                'loopback2',
                'blogger',
                'etsy',
                'facebook',
                'flickr',
                'foursquare',
                'github',
                'googleplus',
                'instagram',
                'linkedin',
                'reddit',
                'runkeeper',
                'twitter',
                'soundcloud',
                'wordpress',
                'vimeo',
                'youtube',
            ])}
        )

    def test_post(self):
        return self.verify_not_supported(path='/api', method='POST')

    def test_put(self):
        return self.verify_not_supported(path='/api', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/api', method='DELETE')


class TestApiOneHandler(TestHandler):
    def test_get_with_unknown_service(self):
        return self.get_and_verify(
            path='/api/no_such_service',
            response_code=404,
            result=error_format("Service 'no_such_service' unknown"),
        )

    def test_get_on_loopback(self):
        self.maxDiff = 100000
        return self.get_and_verify(
            path='/api/loopback',
            response_code=200,
            list_as_set=True,
            result={
                'methods': {
                    'GET': {
                        'most_recent_activity': "The most recent activity on this service's feed",
                        'fortytwo': 'Returns the string "fortytwo"',
                        'fortytwo_interval': 'Returns the string "fortytwo" over time',
                        'ten': 'Returns the string "10"',
                        'ten_interval': 'Returns the string "10" over time',
                        'time': 'Returns the current time in seconds since epoch',
                        'time_interval': 'Returns the current time in seconds since epoch over time',
                        'random': 'Returns a random number between 1 and 999,999',
                        'random_interval': 'Returns a series of random numbers between 1 and 999,999',
                        'broken': 'Returns a 500 error',
                        'sleep': 'Sleeps for the time in the "data" string (default 0.1s)',
                        'whoami': 'Returns the client name in the "data" string',
                        'profile': 'Returns a random profile',
                        'other_profile': 'Returns a random profile',
                        'num_foo': 'Number of foos',
                        'num_foo_interval': 'Number of foos over time',
                    },
                    'POST': {
                        'sleep_post': 'Sleeps for the time in the "data" string (default 0.1s)',
                    },
                },
            },
        )

    def test_post(self):
        return self.verify_not_supported(path='/api/foo', method='POST')

    def test_put(self):
        return self.verify_not_supported(path='/api/foo', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/api/foo', method='DELETE')


class TestApiMeth(TestHandler):
    def test_get_bad_service(self):
        return self.get_and_verify(
            path='/api/no_such_service/profile',
            response_code=404,
            result=error_format("Service 'no_such_service' unknown"),
        )

    def test_post_bad_service(self):
        return self.post_and_verify(
            path='/api/no_such_service/profile',
            response_code=404,
            result=error_format("Service 'no_such_service' unknown"),
        )

    def test_get_bad_method(self):
        return self.get_and_verify(
            path='/api/loopback/no_such_method',
            response_code=404,
            result=error_format("Method 'no_such_method' on service 'loopback' unknown"),
        )

    def test_post_bad_method(self):
        return self.post_and_verify(
            path='/api/loopback/no_such_method',
            response_code=404,
            result=error_format("Method 'no_such_method' on service 'loopback' unknown"),
        )

    def test_get_unauthorized_no_guids(self):
        return self.get_and_verify(
            path='/api/loopback/time',
            response_code=401,
            result=error_format("User not authorized"),
        )

    def test_post_unauthorized_no_guids(self):
        return self.post_and_verify(
            path='/api/loopback/sleep_post',
            response_code=401,
            result=error_format("User not authorized"),
        )

    def test_get_unauthorized_bad_guid(self):
        return self.get_and_verify(
            path='/api/loopback/time',
            args=dict(guid='asdf'),
            response_code=401,
            result=error_format("User not authorized"),
        )

    def test_post_unauthorized_bad_guid(self):
        return self.post_and_verify(
            path='/api/loopback/sleep_post',
            args=dict(guid='asdf'),
            response_code=401,
            result=error_format("User not authorized"),
        )

    @defer.inlineCallbacks
    def test_get_guid_for_wrong_service(self):
        yield self.set_authorization(service_name='loopback2')
        yield self.get_and_verify(
            path='/api/loopback/time',
            args=dict(guid=self.uuid),
            response_code=401,
            result=error_format("User not authorized"),
        )

    @defer.inlineCallbacks
    def test_post_guid_for_wrong_service(self):
        yield self.set_authorization(service_name='loopback2')
        yield self.post_and_verify(
            path='/api/loopback/sleep_post',
            args=dict(guid=self.uuid),
            response_code=401,
            result=error_format("User not authorized"),
        )

    @defer.inlineCallbacks
    def test_get_unauthorized_too_many_guids(self):
        yield self.set_authorization(
            user_id='a1234', token='some token',
        )
        first_uuid = self.uuid
        yield self.set_authorization(
            user_id='b2345', token='some other token',
        )
        yield self.get_and_verify(
            path='/api/loopback/time',
            args=dict(guid=[first_uuid, self.uuid]),
            response_code=401,
            result=error_format("Too many GUIDs"),
        )

    @defer.inlineCallbacks
    def test_post_unauthorized_too_many_guids(self):
        yield self.set_authorization(
            user_id='a1234', token='some token',
        )
        first_uuid = self.uuid
        yield self.set_authorization(
            user_id='b2345', token='some other token',
        )
        yield self.post_and_verify(
            path='/api/loopback/sleep_post',
            args=dict(guid=[first_uuid, self.uuid]),
            response_code=401,
            result=error_format("Too many GUIDs"),
        )

    @defer.inlineCallbacks
    def test_loopback_time(self):
        yield self.set_authorization()
        yield self.write_value(method='time', data=1234)

        yield self.get_and_verify(
            path='/api/loopback/time',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': 1234},
        )

    @defer.inlineCallbacks
    def test_loopback_sleep_post(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/api/loopback/sleep_post',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': '0.1'},
        )

    @defer.inlineCallbacks
    def test_loopback_whoami1(self):
        yield self.set_authorization()

        yield self.get_and_verify(
            path='/api/loopback/whoami',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': 'testing'},
        )

    @defer.inlineCallbacks
    def test_loopback_whoami2(self):
        yield self.set_authorization(client_name='testing')

        yield self.get_and_verify(
            path='/api/loopback/whoami',
            headers={'X-Client': ['testing']},
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': 'testing'},
        )

    @defer.inlineCallbacks
    def test_random_interval(self):
        yield self.set_authorization()

        yield self.write_value(
            timestamp=100, method='random', data=1234,
        )

        yield self.get_and_verify(
            path='/api/loopback/random_interval',
            args=dict(guid=self.uuid, start=50, end=80),
            response_code=200,
            result={'data': []},
        )

        yield self.get_and_verify(
            path='/api/loopback/random_interval',
            args=dict(guid=self.uuid, start=50, end=150),
            response_code=200,
            result={'data': [
                {'num':1234, 'timestamp': '100'},
            ]},
        )

        yield self.write_value(
            timestamp=200, method='random', data=12345,
        )

        yield self.get_and_verify(
            path='/api/loopback/random_interval',
            args=dict(guid=self.uuid, start=50, end=250),
            response_code=200,
            result={'data': [
                {'num': 1234, 'timestamp': '100'},
                {'num': 12345, 'timestamp': '200'},
            ]},
        )

    @defer.inlineCallbacks
    def test_loopback_broken(self):
        yield self.set_authorization()

        yield self.get_and_verify(
            path='/api/loopback/broken',
            args=dict(guid=self.uuid),
            response_code=500,
            result=error_format('500 This method is intentionally broken'),
        )

    def test_put(self):
        return self.verify_not_supported(path='/api/loopback/time', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/api/loopback/time', method='DELETE')

    @defer.inlineCallbacks
    def test_client_servicename_mapping(self):
        # Service names are Lightning's versions internally
        yield self.set_authorization(
            service_name='loopback2', client_name='testing2',
        )

        # Can use our name
        response = yield self.get_and_verify(
            path='/api/LB2/time',
            headers={'X-Client': ['testing2']},
            args=dict(guid=self.uuid),
            response_code=200,
        )
        self.assertRegexpMatches(response.body['data'], r'\d+')

        # Can use lightning's name name
        response = yield self.get_and_verify(
            path='/api/loopback2/time',
            headers={'X-Client': ['testing2']},
            args=dict(guid=self.uuid),
            response_code=200,
        )
        self.assertRegexpMatches(response.body['data'], r'\d+')

        # When we request a list of services, we get back our names
        yield self.get_and_verify(
            path='/api',
            headers={'X-Client': ['testing2']},
            response_code=200,
            list_as_set=True,
            result={'services': set([
                'loopback',
                'LB2',
                'blogger',
                'etsy',
                'facebook',
                'flickr',
                'foursquare',
                'github',
                'googleplus',
                'linkedin',
                'reddit',
                'runkeeper',
                'instagram',
                'soundcloud',
                'twitter',
                'wordpress',
                'vimeo',
                'youtube',
            ])},
        )
