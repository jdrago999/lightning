from __future__ import absolute_import

from .base import TestHandler

from lightning.service.loopback import LoopbackWeb, Loopback2Web
from lightning.error import error_format
from twisted.internet import defer


class TestStreamHandler(TestHandler):
    def test_get_no_guids(self):
        return self.get_and_verify(
            path='/stream',
            response_code=400,
            result=error_format("No GUIDs provided"),
        )

    def test_get_unknown_guid(self):
        return self.get_and_verify(
            path='/stream',
            args=dict(guid='asdf'),
            response_code=400,
            result=error_format("Unknown GUIDs provided"),
        )

    @defer.inlineCallbacks
    def test_get_wrong_service_guid(self):
        yield self.set_authorization(client_name='testing2')
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid),
            response_code=400,
            result=error_format("Unknown GUIDs provided"),
        )

    @defer.inlineCallbacks
    def test_get_multiple_uuids_same_service(self):
        yield self.set_authorization(user_id='1234')
        uuid1 = self.uuid
        yield self.set_authorization(user_id='2345')
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=[uuid1, self.uuid]),
            response_code=400,
            result=error_format("Multiple GUIDs for one service provided"),
        )

    @defer.inlineCallbacks
    def test_get_bad_service(self):
        yield self.set_authorization(user_id='2345')
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, service='no_such_service'),
            response_code=404,
            result=error_format("Service 'no_such_service' unknown"),
        )

    @defer.inlineCallbacks
    def test_get_bad_uuid_for_service(self):
        yield self.set_authorization()
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, service='loopback2'),
            response_code=400,
            result=error_format("Unknown GUIDs provided"),
        )

    @defer.inlineCallbacks
    def test_get_bad_num(self):
        yield self.set_authorization()
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, num='a'),
            response_code=400,
            result=error_format("Bad value for 'num'"),
        )

    @defer.inlineCallbacks
    def test_get_bad_timestamp(self):
        yield self.set_authorization()
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, timestamp='a'),
            response_code=400,
            result=error_format("Bad value for 'timestamp'"),
        )

    @defer.inlineCallbacks
    def test_get_bad_forward(self):
        yield self.set_authorization()
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, forward='a'),
            response_code=400,
            result=error_format("Bad value for 'forward'"),
        )

    @defer.inlineCallbacks
    def test_get_no_data(self):
        self.skip_me('need to rethink the stream tests')
        yield self.set_authorization()
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': []},
        )

    @defer.inlineCallbacks
    def test_get_one_service(self):
        self.skip_me('need to rethink the stream tests')
        self.maxDiff = 10000

        yield self.set_authorization()

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': []},
        )

        yield self.get_service('loopback').daemon_object().create_feed_entry(
            uuid=self.uuid,
            timestamp=100,
            feed_type='foo',
            feed_id='1111',
            user_id='1234',
            user_name='joe',
            profile_url='',
            picture_url='',
            text='',
            testcase=self,
        )

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': '',
                },
            ]},
        )

        yield self.get_service('loopback').daemon_object().create_feed_entry(
            uuid=self.uuid,
            timestamp=220,
            feed_type='foo',
            feed_id='1112',
            user_id='1234',
            user_name='joe',
            profile_url='',
            picture_url='',
            text='some text',
            testcase=self,
        )

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, start=0, end=300),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '220',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1112',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': '',
                },
            ]},
        )

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=self.uuid, start=0, end=300, num=1),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '220',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1112',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )

    @defer.inlineCallbacks
    def test_get_two_services(self):
        self.skip_me('need to rethink the stream tests')
        self.maxDiff = 10000

        yield self.set_authorization()
        uuids = [self.uuid]
        authz = [self.authorization]
        yield self.set_authorization(service_name='loopback2')
        uuids.append(self.uuid)
        authz.append(self.authorization)

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[0]),
            response_code=200,
            result={'data': []},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[1]),
            response_code=200,
            result={'data': []},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids),
            response_code=200,
            result={'data': []},
        )

        yield self.get_service('loopback').daemon_object().create_feed_entry(
            uuid=uuids[0],
            timestamp=100,
            feed_type='foo',
            feed_id='1111',
            user_id='1234',
            user_name='joe',
            profile_url='',
            picture_url='',
            text='some text',
            testcase=self,
        )

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[0]),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[1]),
            response_code=200,
            result={'data': []},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )

        yield self.get_service('loopback2').daemon_object().create_feed_entry(
            uuid=uuids[1],
            timestamp=220,
            feed_type='bar',
            feed_id='1111',
            user_id='2345',
            user_name='jane',
            profile_url='http://someplace.com/profile/jane',
            picture_url='http://someplace.com/picture/jane',
            text='some text',
            testcase=self,
        )

        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[0]),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids[1]),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '220',
                    'service': 'loopback2',
                    'feed_type': 'bar',
                    'feed_id': '1111',
                    'user_id': '2345',
                    'user_name': 'jane',
                    'profile_url': 'http://someplace.com/profile/jane',
                    'picture_url': 'http://someplace.com/picture/jane',
                    'text': 'some text',
                },
            ]},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '220',
                    'service': 'loopback2',
                    'feed_type': 'bar',
                    'feed_id': '1111',
                    'user_id': '2345',
                    'user_name': 'jane',
                    'profile_url': 'http://someplace.com/profile/jane',
                    'picture_url': 'http://someplace.com/picture/jane',
                    'text': 'some text',
                },
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )

        # Verify that if a service is specified, then only its data is returned
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids, service='loopback'),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '100',
                    'service': 'loopback',
                    'feed_type': 'foo',
                    'feed_id': '1111',
                    'user_id': '1234',
                    'user_name': 'joe',
                    'profile_url': '',
                    'picture_url': '',
                    'text': 'some text',
                },
            ]},
        )
        yield self.get_and_verify(
            path='/stream',
            args=dict(guid=uuids, service='loopback2'),
            response_code=200,
            result={'data': [
                {
                    'timestamp': '220',
                    'service': 'loopback2',
                    'feed_type': 'bar',
                    'feed_id': '1111',
                    'user_id': '2345',
                    'user_name': 'jane',
                    'profile_url': 'http://someplace.com/profile/jane',
                    'picture_url': 'http://someplace.com/picture/jane',
                    'text': 'some text',
                },
            ]},
        )
