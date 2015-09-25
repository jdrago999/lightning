"""
This is where the base classes for the handlers live.
"""

from __future__ import absolute_import

from lightning.error import error_format
from lightning.server import JsonErrorPage
import logging
import json
from twisted.internet import defer
from twisted.web.resource import Resource
from twisted.web import http


class JsonNoResource(JsonErrorPage):

    def __init__(self, message="Sorry. No luck finding that resource."):
        JsonErrorPage.__init__(self, http.NOT_FOUND,
                               "No Such Resource",
                               message)


class HandlerError(Exception):

    def __init__(self, message, code):
        Exception.__init__(self, message)
        self.code = code


class HandlerBase(Resource):

    'This is the base class for all handlers'

    def __init__(self, application):
        self.application = application
        Resource.__init__(self)

    def getChild(self, path, request):
        return JsonNoResource("'%s' not found" % request.uri)

    # Add caching here
    def get_client_name(self, request):
        "Retrieve the client name from the request headers"
        return request.getHeader('X-Client') or "testing"

    def _get_client_servicename_mapping(self, request):
        "Get the client's servicename mapping, if any."
        mapping = {
            'testing1': {
                'FB': 'facebook',
                'TW': 'twitter',
                'INS': 'instagram',
                'FOURS': 'foursquare',
                'LinkedIn': 'linkedin',
            },
            'testing2': {
                'LB2': 'loopback2',
            },
        }
        return mapping.get(self.get_client_name(request), dict())

    def decode_client_servicename(self, name, request):
        "Decode what the client gave us for servicename"
        mapping = self._get_client_servicename_mapping(request)

        # If we don't find a match for either the client or the service name
        # within the service, just continue with the service name we have.
        return mapping.get(name, name)

    def encode_client_servicename(self, name, request):
        "Encode what we're giving the client for servicename"
        mapping = {
            v: k for k, v in self._get_client_servicename_mapping(request).items()
        }
        return mapping.get(name, name)

    def get_service(self, name, request):
        "Retrieve the service object based on whatever the client gave us"
        name = self.decode_client_servicename(name, request)
        return self.application.services[name]

    def finish(self, request):
        if not request.finished and not request._disconnected:
            request.finish()

    def write(self, request, content, status=200):
        "Decorate the write() method with an automatic status-setting"
        if not request.finished:
            if status != 200:
                request.setResponseCode(status)
            request.setHeader('Content-Type', 'application/json')
            request.write(json.dumps(content).encode('utf-8'))

    def write_error(self, request, exc, status=500):
        "Decorate the write_error() method with useful JSONification"
        if status == 404:
            error = "'%s' not found" % (self.request.path)
        elif status == 405:
            error = "'%s' not supported for '%s'" % (
                self.request.method, self.request.path
            )
        elif status == 500:
            email_message = []

            if exc:
                # Prepare the items for
                email_message.append('%s - (REMOTE IP: %s) %s %s' % (
                    status,
                    request.getClientIP(),
                    request.method,
                    request.uri
                ))

                email_message.append('HEADERS: ' + str(request.requestHeaders))

                # (error_type, error, traceback) = kwargs['exception'].exc_info
                # append to the email message
                # email_message.append('ERROR TYPE: ' + str(error_type))
                # email_message.append('STACK TRACE:\n' + ''.join(format_list(extract_tb(traceback))))

                try:
                    error = exc.log_message
                # This means it wasn't an HTTPError
                except AttributeError as e:
                    error = str(exc)
            else:
                error = 'Internal Server Error'

            # add the specific email error to the top of the email
            email_message.insert(0, 'ERROR: ' + error)

            # send the email
            self.application.email.send(
                subject='ERROR: %s [%s %s]' % (
                    error,
                    request.method,
                    request.uri
                ),
                message='\n\n'.join(email_message)
            )
            # write to log
            logging.error(error)

        request.setResponseCode(status)
        self.write(request, error_format(error), status)

    def get_argument(self, request, name, default=[]):
        arg_array = request.args.get(name, [])
        if len(arg_array) == 0:
            return default
        else:
            return arg_array[0]

    def get_arguments(self, request, name):
        return request.args.get(name, [])

    def arguments(self, request):
        "Return all the arguments."
        return {k: self.get_argument(request, k) for k in request.args.keys()}

    def get_json_body(self, request, required_keys=[]):
        """Return the JSON body of a POST request."""
        try:
            json_body = json.loads(request.content.getvalue())
        except ValueError:
            raise HandlerError("POST body not a legal JSON value", 400)
        if type(json_body) != dict:
            raise HandlerError("POST body not an object", 400)

        if not set(required_keys) <= set(json_body.keys()):
            diff = set(required_keys) - set(json_body.keys())
            diff = "', '".join(diff)
            raise HandlerError("POST body does not include '%s'" % diff, 400)
        return json_body

    def set_header(self, request, field, value):
        """Set the header on the request.
        Make  sure that the field and value are not unicode, as twisted.web
        hates that"""
        field = field.encode('utf-8')
        value = value.encode('utf-8')
        request.setHeader(field, value)

    @defer.inlineCallbacks
    def live_request(self, service, method_name, authorization, arguments=None):
        """Make a live request for a method.
        This is used to grab data for a method if it's been requested but
        we don't have data for it in the daemon yet.
        """
        daemon = service.daemon_class(
            config=self.application.config,
            datastore=self.application.db,
        )
        if hasattr(daemon, method_name):
            result = yield getattr(daemon, method_name)(
                authorization=authorization,
                arguments=arguments,
            )
        else:
            result = yield getattr(service, method_name)(
                authorization=authorization,
                arguments=arguments,
            )
        defer.returnValue(result)
