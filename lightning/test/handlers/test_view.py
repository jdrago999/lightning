from __future__ import absolute_import

from .base import TestHandler
from twisted.internet import defer
import json
from lightning.error import error_format


class TestViewHandler(TestHandler):
    def test_get_no_views(self):
        return self.get_and_verify(
            path='/view',
            response_code=200,
            list_as_set=True,
            result={'views': set()},
        )

    @defer.inlineCallbacks
    def test_add_view(self):
        # Add view:foo
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        # Check if view:foo is there
        yield self.get_and_verify(
            path='/view',
            response_code=200,
            list_as_set=True,
            result={'views': set(['foo'])},
        )
        yield self.get_and_verify(
            path='/view/foo',
            response_code=200,
            result={'definition': [
                {'service': 'loopback', 'method': 'num_foo'},
                {'service': 'loopback', 'method': 'random'},
            ]},
        )

    def _test_post_error(self, args, error):
        return self.post_and_verify(
            path='/view',
            args=args,
            response_code=400,
            result=error_format(error),
        )

    def test_post_view_no_params(self):
        return self._test_post_error(
            args=None,
            error="POST body not a legal JSON value",
        )

    def test_post_view_not_json_body(self):
        return self._test_post_error(
            args='[]',
            error="POST body not an object",
        )

    def test_post_view_missing_name_and_definition(self):
        return self._test_post_error(
            args='{}',
            error="POST body does not include 'definition', 'name'",
        )

    def test_post_view_missing_name(self):
        return self._test_post_error(
            args=json.dumps(dict(
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                ]
            )),
            error="POST body does not include 'name'",
        )

    def test_post_name_not_string(self):
        return self._test_post_error(
            args=json.dumps({"name": [], "definition": 1}),
            error="'name' is not a string",
        )

    def test_post_missing_definition(self):
        return self._test_post_error(
            args=json.dumps({"name": "foo"}),
            error="POST body does not include 'definition'",
        )

    def test_post_view_definition_not_list(self):
        return self._test_post_error(
            args=json.dumps(dict(name='foo', definition=1)),
            error=["'definition' is not a list"],
        )

    def test_post_view_definition_empty(self):
        return self._test_post_error(
            args=json.dumps(dict(name='foo', definition=[])),
            error=["'definition' is empty"],
        )

    def test_post_view_definition_0_non_object(self):
        return self._test_post_error(
            args=json.dumps(dict(name='foo', definition=[1])),
            error=["0: Received non-object"],
        )

    def test_post_view_definition_0_missing_service(self):
        return self._test_post_error(
            args=json.dumps(dict(name='foo', definition=[{}])),
            error=["0: Missing 'service'"],
        )

    def test_post_view_definition_0_missing_method(self):
        return self._test_post_error(
            args=json.dumps(dict(name='foo', definition=[{"service":1}])),
            error=["0: Missing 'method'"],
        )

    def test_post_view_definition_0_extra_keys(self):
        return self._test_post_error(
            args=json.dumps(dict(
                name='foo',
                definition=[{"service":1, "method":1, "x":1}],
            )),
            error=["0: Received unexpected keys"],
        )

    def test_post_view_definition_0_bad_service(self):
        return self._test_post_error(
            args=json.dumps(dict(
                name='foo',
                definition=[{"service":1, "method":1}],
            )),
            error=["0: Service '1' unknown"],
        )

    def test_post_view_definition_0_bad_method(self):
        return self._test_post_error(
            args=json.dumps(dict(
                name='foo',
                definition=[{"service":"loopback", "method":1}],
            )),
            error=["0: Method '1' on service 'loopback' unknown"],
        )

    def test_post_view_definition_two_errors(self):
        return self._test_post_error(
            args=json.dumps(dict(
                name='foo',
                definition=[{}, 1],
            )),
            error=[
                "0: Missing 'service'",
                "1: Received non-object",
            ],
        )

    def test_put(self):
        return self.verify_not_supported(path='/view', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/view', method='DELETE')


class TestViewOneHandler(TestHandler):
    @defer.inlineCallbacks
    def test_single_view_operations(self):
        # Delete view:foo and fail
        yield self.delete_and_verify(
            path='/view/foo',
            response_code=404,
            result=error_format("View 'foo' unknown"),
        )

        # Get view:foo and fail
        yield self.get_and_verify(
            path='/view/foo',
            response_code=404,
            result=error_format("View 'foo' unknown"),
        )

        # Add view:foo
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        # Try to duplicate add view:foo and fail
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                ],
            )),
            response_code=409,
            result=error_format("View 'foo' already exists"),
        )

        # Add view:bender
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='bender',
                definition=[
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'bender' created"},
        )

        # Get view:foo and view:bender
        yield self.get_and_verify(
            path='/view',
            response_code=200,
            list_as_set=True,
            result={'views': set(['foo', 'bender'])},
        )

        # Check if view:foo has correct value
        yield self.get_and_verify(
            path='/view/foo',
            response_code=200,
            result={
                'definition': [{'service': 'loopback', 'method': 'num_foo'}],
            },
        )

        # Check if view:bender has correct value
        yield self.get_and_verify(
            path='/view/bender',
            response_code=200,
            result={
                'definition': [{'service': 'loopback', 'method': 'random'}],
            },
        )

        # Delete view:foo
        yield self.delete_and_verify(
            path='/view/foo',
            response_code=200,
            result={
                'definition': [{'service': 'loopback', 'method': 'num_foo'}],
            },
        )

        # Delete view:foo and fail
        yield self.delete_and_verify(
            path='/view/foo',
            response_code=404,
            result=error_format("View 'foo' unknown"),
        )

        # Check that we only have view:bender
        yield self.get_and_verify(
            path='/view',
            response_code=200,
            list_as_set=True,
            result={'views': set(['bender'])},
        )

        # Check if view:bender has correct value
        yield self.get_and_verify(
            path='/view/bender',
            response_code=200,
            result={
                'definition': [{'service': 'loopback', 'method': 'random'}],
            },
        )

    def test_post(self):
        return self.post_and_verify(
            path='/view/foo',
            respose_code=400,
            result={
                'error': {'message': "Missing URI Parameter: 'invalidate'"}
            })

    def test_put(self):
        return self.verify_not_supported(path='/view/foo', method='PUT')


class TestApplyViewHandler(TestHandler):
    def test_get_view_unknown(self):
        return self.get_and_verify(
            path='/view/foo/invoke',
            response_code=404,
            result=error_format("View 'foo' unknown"),
        )

    @defer.inlineCallbacks
    def test_get_view_no_guid(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            response_code=401,
            result=error_format("User not authorized"),
        )

    @defer.inlineCallbacks
    def test_get_view_wrong_guid(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token', service_name='testing2',
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
            ),
            response_code=404,
            result={
                'result': [],
                'errors': [
                    {'service': 'loopback', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                    {'service': 'loopback', 'method': 'random', 'message': 'User not authorized', 'code': 404},
                ],
            }
        )

    # Add tests for:
    # * view has two methods in two services
    # 1 GUIDs passed, no matches
    @defer.inlineCallbacks
    def test_get_doubleview_one_guid_no_matches(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token', service_name='testing2',
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
            ),
            response_code=404,
            result={
                'errors': [
                    {'service': 'loopback', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [],
            }
        )

    # 1 GUIDs passed, matches
    @defer.inlineCallbacks
    def test_get_doubleview_one_guid_one_matches(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )
        yield self.write_value(method='num_foo', data='30')

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
            ),
            response_code=206,
            result={
                'errors': [
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                ],
            }
        )

    # 2 GUIDs passed, no matches
    @defer.inlineCallbacks
    def test_get_doubleview_two_guids_no_matches(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token', client_name='testing2'
        )
        uuid_one = self.uuid
        yield self.set_authorization(
            user_id='2345', token='some token', client_name='testing2'
        )
        uuid_two = self.uuid

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, uuid_two],
            ),
            response_code=404,
            result={
                'errors': [
                    {'service': 'loopback', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [],
            }
        )

    # 2 GUIDs passed, one match
    @defer.inlineCallbacks
    def test_get_doubleview_two_guids_one_matches(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )
        uuid_one = self.uuid

        # Must write_value() for this user before the next set_authorization
        yield self.write_value(method='num_foo', data='30')

        # First, verify that we can handle bad GUIDs with good ones.
        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=['fake_uuid', uuid_one],
            ),
            response_code=206,
            result={
                'errors': [
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                ],
            }
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, 'fake_uuid'],
            ),
            response_code=206,
            result={
                'errors': [
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                ],
            }
        )

        yield self.set_authorization(
            user_id='2345', token='some token', client_name='testing2'
        )
        uuid_two = self.uuid

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, uuid_two],
            ),
            response_code=206,
            result={
                'errors': [
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                ],
            }
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_two, uuid_one],
            ),
            response_code=206,
            result={
                'errors': [
                    {'service': 'loopback2', 'method': 'num_foo', 'message': 'User not authorized', 'code': 404},
                ],
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                ],
            }
        )

    # 2 GUIDs passed, two matches
    @defer.inlineCallbacks
    def test_get_doubleview_two_guids_two_matches(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )
        uuid_one = self.uuid

        # Must write_value() for this user before the next set_authorization
        yield self.write_value(method='num_foo', data='30')

        yield self.set_authorization(
            user_id='2345', token='some token', service_name='loopback2'
        )
        uuid_two = self.uuid
        yield self.write_value(method='num_foo', data='40')

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, uuid_two],
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'loopback', 'method': 'num_foo',
                        'num': 30,
                    },
                    {
                        'service': 'loopback2', 'method': 'num_foo',
                        'num': 40,
                    },
                ],
            }
        )

    @defer.inlineCallbacks
    def test_get_view_multiple_guids_one_service(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234',
        )
        uuid_one = self.uuid

        yield self.set_authorization(
            user_id='2345',
        )
        uuid_two = self.uuid

        response = yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, uuid_two],
            ),
            response_code=400,
        )

        # check error structure
        self.assertRegexpMatches(
            response.body['error']['message'],
            r"Multiple GUIDs '[\w-]+,[\w-]+' provided for service '%s'" % (
                'loopback'
            )
        )

        # check for uuids
        self.assertTrue(uuid_one in response.body['error']['message'])
        self.assertTrue(uuid_two in response.body['error']['message'])

    @defer.inlineCallbacks
    def test_get_view_multiple_guids_same_guid(self):
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234',
        )
        uuid_one = self.uuid

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=[uuid_one, uuid_one],
            ),
            response_code=400,
            result=error_format("Duplicate GUIDs '%s' provided" % uuid_one),
        )

    @defer.inlineCallbacks
    def test_get_loopback_view(self):
        # Create a view
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'num_foo'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )

        yield self.write_value(method='num_foo', data='30')
        yield self.write_value(method='random', data='40')

        # Invoke the view and verify the result
        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
            ),
            response_code=200,
            result={
                'result': [
                    {'service': 'loopback', 'method': 'num_foo', 'num': 30},
                    {'service': 'loopback', 'method': 'random', 'num': 40},
                ],
            }
        )

    @defer.inlineCallbacks
    def test_get_loopback_view_with_error(self):
        # Create a view
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'broken'},
                    {'service': 'loopback', 'method': 'random'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )

        yield self.write_value(method='random', data='40')

        # Invoke the view and verify the result
        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
            ),
            response_code=206,
            result={
                'result': [
                    {'service': 'loopback', 'method': 'broken'},
                    {'service': 'loopback', 'method': 'random', 'num': 40},
                ],
                'errors': [{'message': '500 This method is intentionally broken'}],
            }
        )

    @defer.inlineCallbacks
    def test_get_random_interval_view(self):
        # Create a view
        yield self.post_and_verify(
            path='/view',
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'loopback', 'method': 'random_interval'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            user_id='1234', token='some token',
        )

        yield self.write_value(method='random', data='30', timestamp=100)

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
                start=50, end=80,
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'loopback',
                        'method': 'random_interval',
                        'data': []
                    },
                ],
            },
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
                start=50, end=150,
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'loopback',
                        'method': 'random_interval',
                        'data': [
                            {'num': 30, 'timestamp': '100'},
                        ],
                    },
                ],
            },
        )

        yield self.write_value(method='random', data='40', timestamp=200)

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
                start=50, end=150,
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'loopback',
                        'method': 'random_interval',
                        'data': [
                            {'num': 30, 'timestamp': '100'},
                        ]
                    },
                ],
            }
        )

        yield self.get_and_verify(
            path='/view/foo/invoke',
            args=dict(
                guid=self.uuid,
                start=50, end=250,
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'loopback',
                        'method': 'random_interval',
                        'data': [
                            {'num': 30, 'timestamp': '100'},
                            {'num': 40, 'timestamp': '200'},
                        ],
                    },
                ],
            },
        )

    @defer.inlineCallbacks
    def test_get_loopback2_view(self):
        # Create a view
        yield self.post_and_verify(
            path='/view',
            headers={'X-Client': ['testing2']},
            args=json.dumps(dict(
                name='foo',
                definition=[
                    {'service': 'LB2', 'method': 'num_foo'},
                ],
            )),
            response_code=200,
            result={"success": "View 'foo' created"},
        )

        yield self.set_authorization(
            client_name='testing2', service_name='loopback2',
            user_id='1234', token='some token',
        )

        # Verify the view definition
        yield self.get_and_verify(
            path='/view/foo',
            headers={'X-Client': ['testing2']},
            response_code=200,
            result={'definition': [
                {'service':'LB2', 'method':'num_foo'},
            ]},
        )

        yield self.write_value(method='num_foo', data='40', timestamp=200)
        # Invoke the view and verify the result
        yield self.get_and_verify(
            path='/view/foo/invoke',
            headers={'X-Client': ['testing2']},
            args=dict(
                guid=self.uuid,
            ),
            response_code=200,
            result={
                'result': [
                    {
                        'service': 'LB2',
                        'method': 'num_foo',
                        'num': 40,
                    },
                ],
            },
        )

    def test_post(self):
        return self.verify_not_supported(path='/view/foo/invoke', method='POST')

    def test_put(self):
        return self.verify_not_supported(path='/view/foo/invoke', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/view/foo/invoke', method='DELETE')
