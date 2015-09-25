"""
This is where the Auth handlers live.
"""

from __future__ import absolute_import

from lightning.handlers.base import HandlerBase, HandlerError
from lightning.error import LightningError, error_format
from lightning.model.authorization import Authz

from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET

from datetime import timedelta, datetime
import lightning.service.daemons as daemons
import logging

class AuthBase(HandlerBase):
    'Base class for auth handlers. Currently empty'
    pass


class AuthHandler(AuthBase):

    @defer.inlineCallbacks
    def start_auth(self, request):
        try:
            if not self.get_arguments(request, 'service'):
                self.write(request, error_format("Missing argument 'service'"), 400)
                self.finish(request)
            else:
                service_name = self.get_argument(request, 'service')
                got_error = False
                try:
                    service = self.get_service(self.get_argument(request, 'service'), request)
                except KeyError:
                    got_error = True
                    self.write(request, error_format("Service '%s' unknown" % service_name), 404)
                if not got_error:
                    args = self.arguments(request)
                    del args['service']
                    got_error = False
                    try:
                        auth_url = yield service.start_authorization(
                            client_name=self.get_client_name(request),
                            args=args,
                        )
                    except LightningError as exc:
                        got_error = True
                        self.write(request, exc.error_msg, exc.code)

                    if not got_error:
                        self.write(request, {'redirect': auth_url})
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)

    def render_GET(self, request):
        self.start_auth(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def finish_auth(self, request):
        try:
            if not self.get_arguments(request, 'service'):
                raise HandlerError("Missing argument 'service'", 400)

            service_name = self.get_argument(request, 'service')
            try:
                service = self.get_service(service_name, request)
            except KeyError:
                raise HandlerError("Service '%s' unknown" % service_name, 404)

            client_name = self.get_client_name(request)

            authorization = yield service.finish_authorization(
                client_name=client_name,
                args=self.arguments(request),
            )

            # Upon successful initial authz, enqueue the daemon for right away.
            if authorization.is_new and service.daemon_class.__name__ in daemons.DAEMONS and self.application.redis:
                try:
                    from twistedpyres import ResQ
                    resq = ResQ(redis=self.application.redis)

                    for method in service.daemon_class._recurring:
                        yield resq.enqueue_at(
                            (datetime.now() + timedelta(seconds=1)),
                            service.daemon_class,
                            {
                                'sql': service.datastore.config,
                                'environment': service.environment,
                            },
                            authorization.uuid,
                            method,
                            redis=self.application.redis,
                        )


                except Exception as e:
                    logging.error('Error trying to queue: %s' % e.message)
                    raise e
            self.set_header(request, 'Location', '/auth/%s' % authorization.uuid)
            self.write(request, {'guid': authorization.uuid}, status=201)
            self.finish(request)

            # Set account timestamp after we return a guid since this may be an
            # expensive API call.
            if authorization.is_new:
                if 'account_created_timestamp' in service._methods['GET']:
                    try:
                        yield service.account_created_timestamp(
                            authorization=authorization,
                        )
                    except Exception as e:
                        logging.error('Error getting account timestamp: %s' % e)

        except LightningError as exc:
            self.write(request, exc.error_msg, exc.code)
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            logging.error(exc)
            self.write_error(request, exc)
            self.finish(request)

    def render_POST(self, request):
        self.finish_auth(request)
        return NOT_DONE_YET

    def getChild(self, name, request):
        "delegate sub requests to /auth/{service_name or guid} to the AuthOneHandler"
        return AuthOneHandler(self.application, name)


class AuthOneHandler(AuthBase):
    endpoint = r'/auth/([\d\w-]+)'

    def __init__(self, application, name):
        AuthBase.__init__(self, application)
        self.name = name

    def render_GET(self, request):
        self.show_auth(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def show_auth(self, request):
        try:
            guid = self.name
            authz = yield Authz(
                uuid=guid,
            ).get_token(self.application.db)
            if not authz:
                raise HandlerError("guid '%s' not found" % guid, 404)

            self.write(request, {
                'service_name': authz.service_name,
                'user_id': authz.user_id,
                'account_created_timestamp': authz.account_created_timestamp,
                'guid': guid,
            })
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)



    def render_POST(self, request):
        self.revoke_auth(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def revoke_auth(self, request):
        service_name = self.name
        """Revoke OAuth token callback for service.
        If a user revoke's our application's permissions in the service's
        settings, the service will hit this callback so we can remove the
        user's token and any other data.
        """
        try:
            signed_request = self.get_arguments(request, 'signed_request')
            client_name = self.get_client_name(request)
            if not signed_request:
                raise HandlerError("Missing argument 'signed_request'", 400)

            service = self.get_service(service_name, request)
            user_id = yield service.service_revoke_authorization(
                client_name=client_name,
                args=self.arguments(request)
            )
            ret = yield self.application.db.delete_oauth_token(
                client_name=client_name,
                service_name=service_name,
                user_id=user_id,
            )
            if not ret:
                raise HandlerError('Revocation failed', 404)

            self.write(request, {'success': 'Revocation successful'})
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)


    def render_DELETE(self, request):
        self.delete_auth(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def delete_auth(self, request):
        try:
            guid = self.name
            authz = yield Authz(
                uuid=guid,
            ).get_token(self.application.db)
            if not authz:
                raise HandlerError("guid '%s' not found" % guid, 404)

            # Grab the service.
            service = self.get_service(authz.service_name, request)
            # Delete the token and call the revocation method.
            data_ret = yield defer.gatherResults([
                service.revoke_authorization(
                    authorization={'token': authz.token},
                ),
                self.application.db.delete_user_data(
                    uuid=guid,
                    user_id=authz.user_id,
                    service_name=authz.service_name,
                ),
            ])
            ret = yield self.application.db.delete_oauth_token(
                uuid=guid
            )

            if not ret or not data_ret:
                raise HandlerError('Revocation failed', 404)

            self.write(request, {'success': 'Revocation successful'})
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)

