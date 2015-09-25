from __future__ import absolute_import

from .base import TestHandler
from lightning.error import error_format


class Test_Errors(TestHandler):
    def test_bad_accept_header(self):
        bad_accept = 'something_wrong'
        return self.get_and_verify(
            path='/api',
            headers={'Accept': [bad_accept]},
            response_code=200,
            response_type='application/json',
        )

    def test_unsupported_url_json_response_get(self):
        return self.get_and_verify(
            path='/does/not/exist',
            response_code=404,
            response_type='application/json',
            result=error_format("'/does/not/exist' not found"),
        )

    def test_unsupported_url_json_response_post(self):
        return self.post_and_verify(
            path='/does/not/exist',
            response_code=404,
            response_type='application/json',
            result=error_format("'/does/not/exist' not found"),
        )

    def test_unsupported_url_json_response_put(self):
        return self.put_and_verify(
            path='/does/not/exist',
            response_code=404,
            response_type='application/json',
            result=error_format("'/does/not/exist' not found"),
        )

    def test_unsupported_url_json_response_delete(self):
        return self.delete_and_verify(
            path='/does/not/exist',
            response_code=404,
            response_type='application/json',
            result=error_format("'/does/not/exist' not found"),
        )
