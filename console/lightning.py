from __future__ import absolute_import

import requests
from urllib import urlencode, quote
import json
from urlparse import urlunsplit
from pprint import pprint

class Lightning(object):
    "The connection to Lightning for the console"

    def __init__(self, address, url):
        self.address = address
        self.callback = 'https://%s/service' % url

    def args_to_str(self, args):
        """Convert args dict to querystring format."""
        return '&'.join(
            ['%s=%s' % (k, v) for k, v in args.iteritems()]
        )

    def services(self, args={}):
        """Get array of services."""
        data = self.retrieve(
            path='api',
            args=args,
        )


        content = json.loads(data['content'])

        svc = content['services']


        return [s for s in svc if 'loopback' not in s]

    def views(self, args={}):
        """Get array of views."""
        data = self.retrieve(
            path='view',
            args=args,
        )
        return sorted(json.loads(data['content'])['views'])

    def methods(self, service, args={}):
        """Get array of methods for service."""
        data = self.retrieve(
            path='api/%s' % service,
            args=args,
        )
        return json.loads(data['content'])['methods']['GET']

    def retrieve(self, path, args={}, method='GET', postdata=None):
        """Retrieve path against Lightning."""
        url = urlunsplit([
            'http', self.address,
            path, urlencode(args, doseq=True), '',
        ])
        if postdata:
            resp = getattr(requests, method.lower())(
                url,
                headers={
                    'X-Client': 'lg-console',
                    'Content-Type': 'application/json',
                },
                data=postdata,
            )
        else:
            resp = getattr(requests, method.lower())(
                url,
                headers={
                    'X-Client': 'lg-console',
                },
            )
        return {
            'status': resp.status_code,
            'content': resp.content,
        }

    def start_auth(self, service, args):
        """Start the auth process."""
        args['service'] = service
        args['redirect_uri'] = '%s/%s' % (self.callback, service)
        return self.retrieve(
            path='auth',
            args=args,
        )

    def finish_auth(self, service, args):
        """Finish the auth process."""
        args['service'] = service
        args['redirect_uri'] = '%s/%s' % (self.callback, service)
        url = urlunsplit([
            'http', self.address,
            'auth', '', '',
        ])
        resp = requests.post(
            url,
            args,
            headers={
                'X-Client': 'lg-console',
            },
        )
        return {
            'status': resp.status_code,
            'content': resp.content,
        }

    def revoke_auth(self, service, guid):
        url = urlunsplit([
            'http', self.address,
            'auth/%s'%guid, '', '',
        ])
        resp = requests.delete(
            url,
            headers={
                'X-Client': 'lg-console',
            },
        )
        return {
            'status': resp.status_code,
            'content': resp.content,
        }
