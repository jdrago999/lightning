"""Stream handler class.
Used to handle calls to the stream/feed methods of a service.
"""
from __future__ import absolute_import

from lightning.error import error_format, LightningError
from lightning.handlers.base import HandlerBase, HandlerError
from lightning.service.base import STREAM_TYPES
from lightning.model.authorization import Authz
from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET
import logging
import time

class StreamHandlerBase(HandlerBase):
    """Base class for stream handlers."""

    @defer.inlineCallbacks
    def get_authorizations(self, request):
        """Get authorizations from request arguments.
        Returns:
            An array of Authorization objects.
        Raises:
            A HandlerError indicating any exceptions encountered.
        """
        if self.stream_type and not self.stream_type in STREAM_TYPES:
            raise HandlerError("Stream type '%s' unknown" % self.stream_type, 400)
        guids = self.get_arguments(request, 'guid')
        if len(guids) < 1:
            raise HandlerError('No GUIDs provided', 400)

        services = self.get_arguments(request, 'service')
        for service_name in services:
            try:
                self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

        args = dict(
            uuid=guids,
            client_name=self.get_client_name(request),
        )
        if len(services):
            args['service_name'] = services

        authorizations = yield Authz(**args).get_token(self.application.db)

        if len(authorizations) < 1:
            raise HandlerError('Unknown GUIDs provided', 400)

        check = {}
        for auth in authorizations:
            if check.get(auth.service_name):
                raise HandlerError('Multiple GUIDs for one service provided', 400)
            try:
                self.get_service(auth.service_name, request)
                check[auth.service_name] = auth
            except KeyError:
                raise HandlerError("Service '%s' unknown" % auth.service_name, 404)
        defer.returnValue(authorizations)

    @defer.inlineCallbacks
    def show_stream(self, request):
        try:
            authorizations = yield self.get_authorizations(request)
            defaults = {
                'timestamp': int(time.time()),
                'forward': 0,
                'num': 20,
                'echo': 1,
                'show_private': 0,
            }

            args = {}
            for var in defaults.keys():
                try:
                    args[var] = int(self.get_argument(request, var, defaults[var]))
                except ValueError:
                    raise HandlerError("Bad value for '%s'" % var, 400)

            args['forward'] = (bool)(args['forward'])
            args['stream_type'] = self.stream_type

            feed = []
            errors = []


            def append_to_feed(proto_feeds):
                for proto_feed in proto_feeds:
                    # We could have had an error, which returns None
                    try:
                        if proto_feed[0]:
                            for item in proto_feed[1]:
                                feed.append(item)
                    except TypeError:
                        pass

            def handle_error(exc):
                exc.trap(LightningError)
                exc = exc.value
                errors.append(exc.error_msg['error'])

            # defer.gatherResults() will fail if any of the elements fail. We want to
            # succeed if any of the elements succeed, so use a DeferredList instead.
            yield defer.DeferredList([
                defer.maybeDeferred(self.get_service(auth.service_name, request).get_feed(
                    authorization=auth, **args
                )).addErrback(handle_error)
                for auth in authorizations
            ]).addCallback(append_to_feed)

            feed.sort(key=lambda v: int(v['metadata']['timestamp']), reverse=True)


            result = {'data': feed[0:args['num']]}

            if errors:
                result['errors'] = errors
                logging.error(errors)
            self.write(request, result)
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)

class StreamHandler(StreamHandlerBase):
    endpoint = r'/stream'

    def __init__(self, application):
        StreamHandlerBase.__init__(self, application)
        self.stream_type = None

    def render_GET(self, request):
        self.show_stream(request)
        return NOT_DONE_YET

    def getChild(self, name, request):
        return StreamOneHandler(self.application, name)

class StreamOneHandler(StreamHandlerBase):
    endpoint = r'/stream/([\d\w-]+)'

    def __init__(self, application, stream_type):
        StreamHandlerBase.__init__(self, application)
        self.stream_type = stream_type

    def render_GET(self, request):
        self.show_stream(request)
        return NOT_DONE_YET
