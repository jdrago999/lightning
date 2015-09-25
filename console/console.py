from __future__ import absolute_import

import tornado.web

from .datastore import Datastore
from .lightning import Lightning
import json
from pycket.session import SessionMixin
import os


class Console(tornado.web.Application):
    "The application class for the Lightning console"
    def __init__(self, config={}, **kwargs):
        self.redis_host = 'localhost'
        self.redis_port = 6379
        self.datastore = Datastore(
            config.get('redis', '%s:%s' % (self.redis_host, self.redis_port))
        )
        # URL needed to handle callbacks from services
        self.auth_info = {
            'local': 'lg-local.yoursite.com',
            'beta': 'lg-beta.yoursite.com',
            'preprod': 'lg-pre.yoursite.com',
            'prod': 'www.yoursite.com',
        }
        self.auth_url = self.auth_info[config.get('environment', 'local')]
        self.lightning = Lightning(
            address=config.get('lightning', 'localhost:5000'),
            url=self.auth_url,
        )

        # Order here is important. Ordering is most-specific to least-specific.
        handlers = [
            (r"/img/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(os.path.dirname(__file__), "static/img")}),
            (r"/js/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(os.path.dirname(__file__), "static/js")}),
            (r"/css/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(os.path.dirname(__file__), "static/css")}),
            (r'/authclear/(\w+)', AuthClearHandler),
            (r'/service/(\w+)', AuthCallbackHandler),
            (r'/auth/(\w+)', AuthHandler),
            (r'/', BaseHandler),
        ]

        kwargs['template_path'] = 'console/template'

        # Let's not implement sessions by ourselves.
        # Documentation: https://github.com/diogobaeder/pycket
        kwargs['pycket'] = {
            'engine': 'redis',
            'storage': {
                'host': self.redis_host,
                'port': self.redis_port,
            }
        }
        kwargs['cookie_secret'] = 'lightning_console'
        super(Console, self).__init__(handlers, **kwargs)


class BaseHandler(tornado.web.RequestHandler, SessionMixin):
    """Handle basic Lightning calls."""
    def get(self):
        """Render basic Lightning response."""
        path = self.get_argument('path', None)
        if path:
            val = self.application.lightning.retrieve(
                path=path, method=self.get_argument('method', 'GET'),
                postdata=self.get_argument('postdata', None),
            )
        else:
            val = None
        # Don't use the variable name 'response'. Tornado reserves it.
        self.show_template(path=path, val=val)

    def get_authorizations(self):
        """Get dict of currently auth'd services."""
        authed = dict()
        for service in self.application.lightning.services():
            if self.session.get(service):
                authed[service] = self.session.get(service)
        return authed

    def guid_str(self):
        """Get GUID string for view authorization."""
        authed = self.get_authorizations()
        return '&'.join([('guid=%s' % v) for k, v in authed.iteritems()])

    def show_template(self, template='base', path=None, val=None):
        self.render('base',
            val=val,
            path=path,
            guid_str=self.guid_str(),
            views=self.application.lightning.views(),
            authed_services=self.get_authorizations(),
            services=self.application.lightning.services(),
            methods=self.application.lightning.methods,
            loads=json.loads,
            dumps=json.dumps,
        )


class AuthHandler(BaseHandler, SessionMixin):
    """Handle our authentication calls."""
    def get(self, service):
        """Start the auth process."""
        if service:
            val = self.application.lightning.start_auth(
                service, self.request.arguments
            )
        else:
            val = None
        if val['status'] is 200:
            data = json.loads(val['content'])
            self.redirect(data['redirect'])
        else:
            self.show_template(val=val)


class AuthCallbackHandler(BaseHandler, SessionMixin):
    """Handle our authentication callback."""
    def get(self, service):
        """Pass along args to Lightning."""
        data = None
        if service:
            data = self.application.lightning.finish_auth(
                service, self.request.arguments
            )
            # Auth Successful
            result = json.loads(data['content'])
            if 'guid' in result:
                # Set in session
                self.session.set(service, result['guid'])
        self.show_template(val=data)


class AuthClearHandler(BaseHandler, SessionMixin):
    """Clear our authentication for a service."""
    def get(self, service):
        """Clear our auth for given service."""
        data = {
            'status': 404,
            'content': '{"error": "No auth found for %s"}' % service,
        }
        auths = self.get_authorizations()
        if service in auths:
            # Assume this works properly. How should we behave if it doesn't??
            self.application.lightning.revoke_auth(service, auths[service])
            self.session.delete(service)
            data = {
                'status': 200,
                'content': '{"success": "Auth removed for %s"}' % service,
            }
        self.show_template(val=data)
