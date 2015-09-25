"Generic docstring A"
from __future__ import absolute_import

from lightning.handlers.base import HandlerBase, HandlerError
from lightning.error import error_format, LightningError
from lightning.model.authorization import Authz
from lightning.model.status import Status, StatusCode, StatusMessage

from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET
from collections import Counter
import json


class StatusBase(HandlerBase):
    "Base class for all requests to /status. Currently empty."
    pass


class StatusHandler(StatusBase):
    "Handles resquests to /status"
    endpoint = r'/status'

    def __init__(self, application):
        StatusBase.__init__(self, application)

    def render_POST(self, request):
        self.invoke_post_method(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def invoke_post_method(self, request):
        def handle_db_error(error):
            raise HandlerError("Unable to connect to SQL Server", 500)

        try:
            json_body = self.get_json_body(request, ['guids'])
            guids = json_body['guids']
            # Validate input
            if type(guids) != list:
                raise HandlerError("'guids' is not a list", 400)
            if not len(guids):
                raise HandlerError("'guids' is empty", 400)
            dupes = [k for k,v in Counter(guids).items() if v > 1]
            if len(dupes):
                dupes = "', '".join(dupes)
                raise HandlerError("Duplicate GUIDs '%s' provided" % dupes, 400)

            # Retrieve authorizations
            authorizations = [
                Authz(uuid=g).get_token(self.application.db).addErrback(handle_db_error) for g in guids
            ]
            authorizations = yield defer.DeferredList(authorizations)
            # DeferredList returns (success, result) tuple, just grab results
            authorizations = [a[1] for a in authorizations if a[1]]

            service_names = [a.service_name for a in authorizations]
            services = {s: self.get_service(s, request) for s in service_names}

            ret = None
            try:
                results = []
                def handle_profile_error(error, uuid, service_name, is_refreshable):
                    code = StatusCode.UNKNOWN
                    if error.value.code:
                        code = error.value.code
                    results.append(Status(
                        guid=uuid,
                        code=code,
                        message=error.value.message,
                        service_name=service_name,
                        is_refreshable=is_refreshable
                    ))
                def handle_profile(profile, uuid, service_name, is_refreshable):
                    # Status is OK if we received a profile
                    results.append(Status(
                        guid=uuid,
                        code=StatusCode.OK,
                        message=StatusMessage.OK,
                        service_name=service_name,
                        is_refreshable=is_refreshable
                    ))
                profiles = {}
                for authz in authorizations:
                    is_refreshable = hasattr(services[authz.service_name], 'refresh_token')
                    profiles[authz.service_name] = self.live_request(
                        services[authz.service_name],
                        'profile',
                        authorization=authz
                    ).addCallback(
                        handle_profile,
                        authz.uuid,
                        authz.service_name,
                        is_refreshable
                    ).addErrback(
                        handle_profile_error,
                        authz.uuid,
                        authz.service_name,
                        is_refreshable
                    )
                profiles = yield defer.DeferredList(profiles.values())
                auth_guids = [a.uuid for a in authorizations]
                # GUIDs we haven't received in authorizations don't exist in DB
                for g in guids:
                    if g not in auth_guids:
                        results.append(Status(
                            guid=g,
                            code=StatusCode.NOT_FOUND,
                            message=StatusMessage.NOT_FOUND,
                            service_name=None
                        ))
                ret = {'result': results}
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
