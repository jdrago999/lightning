from __future__ import absolute_import

from .base import TestHandler
from twisted.internet import defer
import json
from lightning.error import error_format

class TestStatusHandler(TestHandler):

    def _test_post_error(self, args, error):
        return self.post_and_verify(
            path='/status',
            args=args,
            response_code=400,
            result=error_format(error),
        )

    @defer.inlineCallbacks
    def test_post_status_bad_guid(self):
        yield self.post_and_verify(
            path='/status',
            args=json.dumps(dict(
                guids=["fake-guid"],
            )),
            response_code=200,
            result={"result": [
                {
                    "guid": 'fake-guid',
                    "code": 404,
                    "message": "GUID not found",
                    "service_name": None,
                    "is_refreshable": None,
                }
            ]},
        )

    @defer.inlineCallbacks
    def test_post_status_bad_token_refreshable(self):
        yield self.set_authorization(
            user_id='1234', token='some bad token', service_name='googleplus',
        )
        yield self.post_and_verify(
            path='/status',
            args=json.dumps(dict(
                guids=[self.uuid],
            )),
            response_code=200,
            result={"result": [
                {
                    "guid": self.uuid,
                    "code": 400,
                    "message": "Bad Parameters",
                    "service_name": "googleplus",
                    "is_refreshable": True,
                }
            ]},
        )

    @defer.inlineCallbacks
    def test_post_status_bad_token_not_refreshable(self):
        yield self.set_authorization(
            user_id='1234', token='some bad token', service_name='facebook',
        )
        yield self.post_and_verify(
            path='/status',
            args=json.dumps(dict(
                guids=[self.uuid],
            )),
            response_code=200,
            result={"result": [
                {
                    "guid": self.uuid,
                    "code": 401,
                    "message": "Invalid access_token",
                    "service_name": "facebook",
                    "is_refreshable": False,
                }
            ]},
        )

    def test_post_status_no_params(self):
        return self._test_post_error(
            args=None,
            error="POST body not a legal JSON value",
        )

    def test_post_status_not_json_body(self):
        return self._test_post_error(
            args='[]',
            error="POST body not an object",
        )

    def test_post_status_missing_guids(self):
        return self._test_post_error(
            args='{}',
            error="POST body does not include 'guids'",
        )

    def test_post_status_guids_not_list(self):
        return self._test_post_error(
            args=json.dumps(dict(guids=1)),
            error="'guids' is not a list",
        )

    def test_post_status_guids_empty(self):
        return self._test_post_error(
            args=json.dumps(dict(guids=[])),
            error="'guids' is empty",
        )

    def test_post_status_guids_one_duplicate(self):
        return self._test_post_error(
            args=json.dumps(dict(guids=["foo", "foo"])),
            error="Duplicate GUIDs 'foo' provided",
        )

    def test_post_status_guids_two_duplicates(self):
        return self._test_post_error(
            args=json.dumps(dict(guids=["foo", "foo", "bar", "bar"])),
            error="Duplicate GUIDs 'foo', 'bar' provided",
        )

    def test_get(self):
        return self.verify_not_supported(path='/status', method='GET')

    def test_put(self):
        return self.verify_not_supported(path='/status', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/status', method='DELETE')
