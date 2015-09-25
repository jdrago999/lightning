"Generic docstring A"
from __future__ import absolute_import

from lightning.handlers.base import HandlerBase, HandlerError
from lightning.error import error_format, LightningError
from lightning.model.authorization import Authz

from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET


class ApiBase(HandlerBase):
    "Base class for all requests to /api. Currently empty."
    pass


class ApiHandler(ApiBase):
    "Handles resquests to /api"

    def render_GET(self, request):
        "Handle get requests"
        # increment api calls counter

        try:
            try:
                self.write(request, {'services': [
                    self.encode_client_servicename(k, request)
                    for k in self.application.services.keys()
                ]})
            except:
                self.write(request, {'services': []})

        except Exception as exc:
            self.write_error(request, exc)

        return ""

    def getChild(self, name, request):
        "delegate sub requests to /api/{service_name} to the ApiOneHandler"
        return ApiOneHandler(self.application, name)


class ApiOneHandler(ApiBase):
    "Handles resquests to /api/(\w+)"

    def __init__(self, application, service_name):
        ApiBase.__init__(self, application)
        self.service_name = service_name

    def render_GET(self, request):
        "Handle get requests"

        try:
            service_name = self.service_name
            try:
                service = self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

            methods = service.methods() or []
            self.write(request, {'methods': methods})

        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
        except Exception as exc:
            self.write_error(request, exc)


        return ""

    def getChild(self, name, request):
        "delegate sub requests to /api/{service_name}/{method_name} to the ApiMethHandler"
        return ApiMethHandler(self.application, self.service_name, name)


class ApiMethHandler(ApiBase):
    "Handles resquests to /api/(\w+)/(\w+)"
    endpoint = r'/api/(\w+)/(\w+)'

    def __init__(self, application, service_name, method_name):
        ApiBase.__init__(self, application)
        self.service_name = service_name
        self.method_name = method_name

    def render_GET(self, request):
        self.invoke_get_method(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def invoke_get_method(self, request):
        "Invoke the current method on the current service"
        service_name = self.service_name
        method_name = self.method_name

        try:
            try:
                service = self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

            if not method_name in service.methods()['GET']:
                raise HandlerError("Method '%s' on service '%s' unknown" % (method_name, service_name), 404)

            guids = self.get_arguments(request, 'guid')
            if not len(guids):
                raise HandlerError("User not authorized", 401)


            authorizations = yield Authz(
                uuid=guids,
                client_name=self.get_client_name(request),
                service_name=self.decode_client_servicename(service_name, request),
            ).get_token(self.application.db)

            if len(authorizations) > 1:
                raise HandlerError('Too many GUIDs', 401)

            elif len(authorizations) != 1:
                raise HandlerError('User not authorized', 401)

            ret = None
            status = 200
            try:
                ret = yield getattr(service, method_name)(
                    authorization=authorizations[0],
                    arguments=self.arguments(request),
                )
                # Make a live request to get the value if the daemon hasn't
                # populated it yet.
                if not ret and method_name == 'profile':
                    ret = yield self.live_request(
                        service,
                        method_name,
                        authorizations[0],
                        self.arguments(request)
                    )
            except LightningError as exc:
                ret = error_format(
                    exc.message,
                    method=method_name,
                    service=service_name,
                    code=exc.code,
                    retry_at=exc.retry_at,
                )
                status = exc.code

            if ret:
                self.write(request, ret, status)
            else:
                self.write(request, {'success': None})
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)

    def render_POST(self, request):
        self.invoke_post_method(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def invoke_post_method(self, request):
        try:
            service_name = self.service_name
            method_name = self.method_name

            try:
                service = self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

            if not method_name in service.methods()['POST']:
                raise HandlerError("Method '%s' on service '%s' unknown" % (method_name, service_name), 404)

            guids = self.get_arguments(request, 'guid')
            if not len(guids):
                raise HandlerError("User not authorized", 401)

            authorizations = yield Authz(
                uuid=guids,
                client_name=self.get_client_name(request),
                service_name=self.decode_client_servicename(service_name, request),
            ).get_token(self.application.db)

            if len(authorizations) > 1:
                raise HandlerError('Too many GUIDs', 401)

            elif len(authorizations) != 1:
                raise HandlerError('User not authorized', 401)

            ret = None
            try:
                ret = yield getattr(service, method_name)(
                    authorization=authorizations[0],
                    arguments=self.arguments(request),
                )
            except LightningError as exc:
                raise HandlerError(exc.error_msg, exc.code)

            if ret:
                self.write(request, ret)
            else:
                self.write(request, {'success': None})
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)
