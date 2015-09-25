from __future__ import absolute_import
from .base import HandlerBase, HandlerError

import json
import logging
from lightning.error import error_format, LightningError
from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET


class ViewHandler(HandlerBase):

    def render_GET(self, request):
        d = self.application.db.get_views()

        def finish(keys):
            self.write(request, {'views': keys})
            self.finish(request)

        def on_error(exc):
            self.write_error(request, exc)
            self.finish(request)


        d.addCallback(finish).addErrback(on_error)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def create_views(self, request):
        try:
            json_body = self.get_json_body(request, ['name', 'definition'])

            if type(json_body['name']) != unicode:
                raise HandlerError("'name' is not a string", 400)

            existing_view = yield self.application.db.view_exists(
                json_body['name'],
            )
            if existing_view or json_body['name'] == 'invalidate':
                error_message = "View '%s' already exists" % json_body['name']
                raise HandlerError(error_message, 409)

            errors = []
            view = json_body['definition']
            if type(view) != list:
                errors.append("'definition' is not a list")
            elif len(view) == 0:
                errors.append("'definition' is empty")
            else:
                for idx, m in enumerate(view):
                    if type(m) != dict:
                        errors.append('%d: Received non-object' % idx)
                        continue

                    if not m.get('service'):
                        errors.append("%d: Missing 'service'" % idx)
                        continue

                    if not m.get('method'):
                        errors.append("%d: Missing 'method'" % idx)
                        continue

                    k = m.keys()
                    if len(k) > 2:
                        errors.append("%d: Received unexpected keys" % idx)
                        continue

                    try:
                        service = self.get_service(m['service'], request)
                    except KeyError:
                        errors.append("%d: Service '%s' unknown" % (idx, m['service']))
                        continue

                    if not m['method'] in service.methods()['GET']:
                        errors.append("%d: Method '%s' on service '%s' unknown" % (idx, m['method'], m['service']))
                        continue

            if len(errors):
                self.write(request, error_format(errors), 400)
                self.finish(request)
            else:
                yield self.application.db.set_view(
                    json_body['name'],
                    json_body['definition'],
                )
                self.write(request, {'success': "View '%s' created" % json_body['name']})
                self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)


    def render_POST(self, request):
        self.create_views(request)
        return NOT_DONE_YET

    def getChild(self, name, request):
        "delegate sub requests to /view/{view_name} to the ViewOneHandler."
        return ViewOneHandler(self.application, name)


class ViewOneHandler(HandlerBase):

    def __init__(self, application, view_name):
        HandlerBase.__init__(self, application)
        self.view_name = view_name

    def render_GET(self, request):
        self.write_view(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def write_view(self, request):
        try:
            name = self.view_name

            view = yield self.application.db.get_view(name)
            if not view:
                self.write(request, error_format("View '%s' unknown" % name), 404)
            else:

                self.write(request, {'definition': view})
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)

    @defer.inlineCallbacks
    def delete_view(self, request):
        try:
            name = self.view_name
            view = yield self.application.db.get_view(name)
            if not view:
                self.write(request, error_format("View '%s' unknown" % name), 404)
            else:
                yield self.application.db.delete_view(name)

                self.write(request, {'definition': view})
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)


    def render_DELETE(self, request):
        self.delete_view(request)
        return NOT_DONE_YET

    def getChild(self, name, request):
        "delegate sub requests to /view/{view_name}/invoke to the ViewOneHandler."
        if name == 'invoke':
            return ApplyViewHandler(self.application, self.view_name)
        else:
            return super(ViewOneHandler, self).getChild(name, request)


class ApplyViewHandler(HandlerBase):
    endpoint = r'/view/(\w+)/invoke'

    def __init__(self, application, view_name):
        HandlerBase.__init__(self, application)
        self.view_name = view_name


    def render_GET(self, request):
        self.invoke_view(request)
        return NOT_DONE_YET

    @defer.inlineCallbacks
    def invoke_view(self, request):
        try:
            name = self.view_name

            view = yield self.application.db.get_view(name)
            if not view:
                raise HandlerError("View '%s' unknown" % name, 404)

            guids = self.get_arguments(request, 'guid')
            if not len(guids):
                raise HandlerError("User not authorized", 401)

            # check for duplicate guids
            guid_dups = set()
            [guid_dups.add(i) for i in guids if i not in guid_dups and guids.count(i) > 1]
            if len(guid_dups):
                raise HandlerError("Duplicate GUIDs '%s' provided" % ','.join(guid_dups), 400)

            authorizations = yield self.application.db.get_oauth_token(
                uuid=guids,
                client_name=self.get_client_name(request),
            )

            # check for guids that share the same service
            services_seen = []
            for a in authorizations:
                if a.service_name in services_seen:
                    # identify problematic guids for the service
                    service_guid_dups = set()
                    [service_guid_dups.add(i.uuid) for i in authorizations if i.service_name == a.service_name and a.uuid not in service_guid_dups]
                    raise HandlerError(
                        "Multiple GUIDs '%s' provided for service '%s'" % (','.join(service_guid_dups), a.service_name),
                        400
                    )
                else:
                    services_seen.append(a.service_name)

            authz_by_service = {}
            results = []
            errors = []
            arguments = self.arguments(request)
            for m in view:
                result = None
                l_servicename = self.decode_client_servicename(m['service'], request)
                if not authz_by_service.get(l_servicename):
                    # TODO(rob): Find a better algorithm than O(N^2)
                    for authorization in authorizations:
                        if authorization.service_name == l_servicename:
                            authz_by_service[l_servicename] = authorization
                            break  # Break out of the else clause as well
                    else:
                        errors.append(
                            error_format(
                                'User not authorized',
                                code=404,
                                service=m['service'],
                                method=m['method'],
                            )['error']
                        )
                        continue

                try:
                    service = self.get_service(m['service'], request)
                    result = yield getattr(service, m['method'])(
                        authorization=authz_by_service[l_servicename],
                        arguments=arguments,
                    )
                    # Make a live request to get the value if the daemon hasn't
                    # populated it yet.
                    if result is None and m['method'] == 'profile':
                        result = yield self.live_request(
                            service,
                            m['method'],
                            authorization=authz_by_service[l_servicename],
                            arguments=arguments,
                        )
                except LightningError as exc:
                    errors.append(exc.error_msg['error'])
                except Exception as exc:
                    errors.append(error_format("%s" % exc)['error'])

                if result is None:
                    result = {}
                elif isinstance(result, list):
                    # XXX(ray): All results need to return a hash. If you're
                    # thinking of returning an array, key it with "data" in a hash.
                    raise LightningError("Expected dict for view result, got an array")
                result['service'] = m['service']
                result['method'] = m['method']

                results.append(result)

            code = 200
            result = {'result': results}

            if errors:
                result['errors'] = errors
                logging.error(errors)
            if errors and result['result']:
                code = 206
            elif errors and not result['result']:
                code = errors[0].get('code', 500)

            self.write(request, result, code)
            self.finish(request)
        except HandlerError as exc:
            self.write(request, error_format(exc.message), exc.code)
            self.finish(request)
        except Exception as exc:
            self.write_error(request, exc)
            self.finish(request)
