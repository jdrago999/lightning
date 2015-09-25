"""
This is where the Data handlers live.
"""

from __future__ import absolute_import

from lightning.error import error_format
from lightning.handlers.base import HandlerBase, HandlerError
from lightning.model.authorization import Authz
from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET
import json
import time



class DataHandler(HandlerBase):
    def getChild(self, name, request):
        "delegate sub requests to /data/{service_name} to the DataServiceHandler"
        return DataServiceHander(self.application, name)

class DataServiceHander(HandlerBase):
    def __init__(self, application, service_name):
        HandlerBase.__init__(self, application)
        self.service_name = service_name

    def getChild(self, name, request):
        "delegate sub requests to /data/{service_name}/{method_name to the DataMethodHandler"
        return DataMethodHandler(self.application, self.service_name, name)


class DataMethodHandler(HandlerBase):
    endpoint = r'/data/(\w+)/(\w+)'

    def __init__(self, application, service_name, method_name):
        HandlerBase.__init__(self, application)
        self.service_name = service_name
        self.method_name = method_name


    def render_POST(self, request):
        self.add_data(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def add_data(self, request):

        try:
            service_name = self.service_name
            method_name = self.method_name

            try:
                service = self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

            if not method_name in service.methods()['GET']:
                raise HandlerError("Method '%s' on service '%s' unknown" % (method_name, service_name), 404)

            guids = self.get_arguments(request, 'guid')
            if not len(guids):
                raise HandlerError("No GUID provided", 400)

            elif len(guids) > 1:
                raise HandlerError("Too many GUIDs provided", 400)

            authorization = yield Authz(
                uuid=guids[0],
                client_name=self.get_client_name(request),
            ).get_token(self.application.db)

            if not authorization:
                raise HandlerError("Unknown GUID provided", 400)

            values = self.get_arguments(request, 'value')
            if not len(values):
                raise HandlerError("No value provided", 400)

            elif len(values) > 1:
                raise HandlerError("Too many values provided", 400)

            timestamp = int(self.get_argument(request, 'timestamp', time.time()))
            try:
                yield service.write_new_value(
                    authorization=authorization,
                    method=method_name,
                    data=json.loads(values[0]),
                    timestamp=timestamp,
                )
            except ValueError:
                raise HandlerError("Invalid JSON provided", 400)

            except KeyError:
                raise HandlerError("Wrong key for data provided", 400)

            self.write(request, {'success': '/%s/%s written' % (service_name, method_name)})
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)
