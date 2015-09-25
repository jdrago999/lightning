"Generic docstring A"
from __future__ import absolute_import

from .base import TestHandler
from lightning.error import error_format
from twisted.internet import defer

import json


class TestDataHandler(TestHandler):
    def test_post_with_unknown_service(self):
        return self.post_and_verify(
            path='/data/no_such_service/no_such_method',
            response_code=404,
            result=error_format("Service 'no_such_service' unknown"),
        )

    def test_post_with_unknown_method(self):
        return self.post_and_verify(
            path='/data/loopback/no_such_method',
            response_code=404,
            result=error_format("Method 'no_such_method' on service 'loopback' unknown"),
        )

    def test_post_no_guids(self):
        return self.post_and_verify(
            path='/data/loopback/time',
            response_code=400,
            result=error_format("No GUID provided"),
        )

    def test_post_unknown_guid(self):
        return self.post_and_verify(
            path='/data/loopback/time',
            args=dict(guid='asdf'),
            response_code=400,
            result=error_format("Unknown GUID provided"),
        )

    def test_post_too_many_guids(self):
        return self.post_and_verify(
            path='/data/loopback/time',
            args=dict(guid=['asdf', 'efgh']),
            response_code=400,
            result=error_format("Too many GUIDs provided"),
        )

    @defer.inlineCallbacks
    def test_post_guid_for_wrong_service(self):
        yield self.set_authorization(client_name='testing2')
        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(guid=self.uuid),
            response_code=400,
            result=error_format("Unknown GUID provided"),
        )

    @defer.inlineCallbacks
    def test_post_no_value(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
            ),
            response_code=400,
            result=error_format("No value provided"),
        )

    @defer.inlineCallbacks
    def test_post_too_many_values(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
                value=['a', 'b'],
            ),
            response_code=400,
            result=error_format("Too many values provided"),
        )

    @defer.inlineCallbacks
    def test_post_bad_value(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
                value='a',
            ),
            response_code=400,
            result=error_format("Invalid JSON provided"),
        )

    @defer.inlineCallbacks
    def test_post_wrong_key(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
                value=json.dumps({'num': 100}),
            ),
            response_code=400,
            result=error_format("Wrong key for data provided"),
        )

    @defer.inlineCallbacks
    def test_post_using_data(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
                value=json.dumps({'data': 100}),
            ),
            response_code=200,
            result={"success": "/loopback/time written"},
        )

        ret = yield self.get_value(
            method='time',
        )
        self.assertEqual(ret, 100)

    @defer.inlineCallbacks
    def test_post_using_num(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/random',
            args=dict(
                guid=self.uuid,
                value=json.dumps({'num': 100}),
            ),
            response_code=200,
            result={"success": "/loopback/random written"},
        )

        ret = yield self.get_value(
            method='random',
        )
        self.assertEqual(ret, 100)

    @defer.inlineCallbacks
    def test_post_using_none(self):
        yield self.set_authorization()

        profile = {
            'first_name': 'joe',
            'last_name': 'smith',
        }

        yield self.post_and_verify(
            path='/data/loopback/other_profile',
            args=dict(
                guid=self.uuid,
                value=json.dumps(profile),
            ),
            response_code=200,
            result={"success": "/loopback/other_profile written"},
        )

        ret = yield self.get_value(
            method='other_profile',
        )
        self.assertEqual(json.loads(ret), profile)

    @defer.inlineCallbacks
    def test_post_setting_timestamp(self):
        yield self.set_authorization()

        yield self.post_and_verify(
            path='/data/loopback/time',
            args=dict(
                guid=self.uuid,
                value=json.dumps({'data': 100}),
                timestamp=50
            ),
            response_code=200,
            result={"success": "/loopback/time written"},
        )

        ret = yield self.get_value_range(
            method='time',
            start=0, end=100,
            testcase=self,
        )
        self.assertEqual(ret, [['50', 100]])

    def test_get(self):
        return self.verify_not_supported(path='/data/loopback/time', method='GET')

    def test_put(self):
        return self.verify_not_supported(path='/data/loopback/time', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/data/loopback/time', method='DELETE')
