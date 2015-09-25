from __future__ import absolute_import

from ..base import TestLightning


class TestHandler(TestLightning):
    def get_service(self, name):
        return self.app.services.get(name)

    def verify_not_supported(self, method, path):
        method = method.upper()
        body = None
        if method == 'POST' or method == 'PUT':
            body = ''
        response = self.fetch(path=path, body=body, method=method)

        def verify(response):
            self.assertEqual(response.code, 405)
            self.assertEqual(response.body, {
                'error': {
                    'message': "'%s' not supported for '%s'" % (method, path),
                }
            })
            return response
        response.addCallback(verify)

        return response
