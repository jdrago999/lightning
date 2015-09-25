"Generic docstring A"
from __future__ import absolute_import

from functools import wraps

from lightning.service.response_filter import ResponseFilter

from lightning.datastore.sql import DatastoreSQL
from lightning.error import (
    Error, ApiMethodError, AuthError, DatastoreError, InvalidRedirectError,
    InvalidTokenError, LightningError, MissingArgumentError, OverCapacityError,
    InsufficientPermissionsError, RateLimitError, RefreshTokenError, ServiceError, SQLError
)
from lightning.model import LimitedDict
from lightning.model.authorization import Authz
from lightning.utils import get_uuid

import cyclone.httpclient
from twisted.internet import defer, reactor
from twistedpyres import ResQ

import base64
import binascii
from datetime import timedelta, datetime, date
from calendar import timegm
import iso8601

from hashlib import sha1
import hmac
from inspect import getmembers
import json
from lightning.recorder import recorder
import logging
import oauth2
import os
import time
from urllib import urlencode, quote_plus
from urlparse import parse_qs, urlsplit, urlunsplit

import newrelic.agent

STREAM_TYPES = ['photos_uploaded', 'reviews']

# This monkeypatching is necessary in order to do a POST with postdata. Tornado
# expects that resumeProducing() is defined. But, Cyclone doesn't provide it.
from cyclone.httpclient import StringProducer
def resumeProducing(self):
    pass
StringProducer.resumeProducing = resumeProducing


def daemon_log(service_name, uuid, method, message):
    return '(%s %s %s) %s' % (service_name, uuid, method, message)


class Service(object):
    "Base class for Services"
    def __init__(self, **kwargs):
        self.environment = kwargs.get('config', {}).get('environment', 'local')

        assert "datastore" in kwargs
        self.datastore = kwargs['datastore']

        self.response_filter = ResponseFilter()
        self.status_errors = {
            400: Error.BAD_PARAMETERS,
            401: Error.INVALID_TOKEN,
            403: Error.RATE_LIMITED,
            404: Error.NOT_FOUND,
            500: Error.UNKNOWN_RESPONSE,
            502: Error.OVER_CAPACITY,
            503: Error.OVER_CAPACITY,
            504: Error.OVER_CAPACITY,
        }
        self.good_statuses = [200, 201]

    def ensure_arguments(self, required, args):
        """
        Ensures that every key listed in the list 'required' exists in the dict
        'args'. If any is missing, a MissingArgumentError is raised listing
        the missing strings. Otherwise, returns True.
        """
        missing = [p for p in required if not args.get(p)]
        if len(missing):
            raise MissingArgumentError(
                "Missing arguments: '%s'" % ("', '".join(missing))
            )
        return True

    def full_url(self, **kwargs):
        'Method for figuring out the URL'

        # Short-circuit if the caller says "I know what I'm doing!"
        if kwargs.get('full_url'):
            return kwargs['full_url']

        assert kwargs.get('path') is not None

        args = kwargs.get('args', dict())

        parsed_url = urlsplit(kwargs.get('base_url', self.endpoint_url))
        return urlunsplit([
            parsed_url.scheme, parsed_url.netloc,
            '%s/%s' % (parsed_url.path, kwargs['path']), urlencode(args), '',
        ])

    def parse_response(self, response, **kwargs):
        """Parse the response"""
        try:
            data = json.loads(response)
        except Exception as exc:
            raise ApiMethodError(exc)

        if kwargs.get('with_sum'):
            # 'num' dict used in parse_response and Default
            # Must change in both places
            data = {'num': sum([1 for x in data.get(kwargs['with_sum'], [])])}
        return data

    def actually_request(self, *args, **kwargs):
        def handle_response(resp):
            if resp.code not in self.good_statuses:
                self.parse_error(
                    resp.code,
                    resp.request.url,
                    resp.headers,
                    resp.body
                )
            return resp

        return cyclone.httpclient.fetch(*args, **kwargs).addCallback(handle_response)

    def request(self, **kwargs):
        "This does all the heavy lifting for doing a web request."

        def handle_response(response):
            if kwargs.get('no_parse'):
                return response
            return self.parse_response(response.body, **kwargs)

        def handle_error(failure):
            """Handle RefreshTokenError from actually_request.
            We need to refresh the token and re-request with our new token.
            """
            failure.trap(RefreshTokenError)
            logging.info('Refreshing token for %s on %s' % (kwargs['authorization'].uuid, self.name))
            return self.refresh_token(**kwargs).addCallback(re_request)

        def re_request(request_args):
            """Make the request again.
            Args: dict, request args to pass along with updated authorization
            """
            return self.request(**request_args)

        return self.actually_request(
            url=kwargs['url'], headers=kwargs.get('headers', dict()),
            method=kwargs.get('method', 'GET'),
            postdata=kwargs.get('body'),
        ).addCallback(handle_response).addErrback(handle_error)

    def transform_paged_response(self, resp):
        """Take the response and tranform it in some way, such as extracting out relevant fields.
        The default implementation here just leaves the response alone"""
        return resp

    def extract_data_array(self, resp, data_name=None):
        """given `resp` a JSON response that should contain a list of results, and the field the contians those
        results (if any), `data_name`, extract that list and return it"""

        if data_name:
            return resp.get(data_name, [])
        else:
            return resp

    def request_with_paging(self, path, callback, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        The assumption is that the callback is doing some sort of useful work,
        likely with an accumulator of some sort.

        This requires that 'paging', 'direction', and 'data_name' be set for
        that service's values.
        """

        stopback = kwargs.get('stopback', lambda: False)
        use_limit_offset_paging = 'offset_field' in kwargs and 'limit_field' in kwargs
        if use_limit_offset_paging:
            # Handle limit/offset and page/per_page paging.  Relevant fields are:
            # offest_field - the name of the field  that we send the offset via.  This controls
            #     which page of results we see.  For page/per_page services, this is the 'page'
            #     field.
            # limit_field - the name field through which we send the limit.
            # limit - how many results per page we recieve.  Genreally, this should be maximum
            #     allowable by the service
            # offset_increase - This is how much the offset field should increase with each page
            #    of results.  This is generally 1 with page/per_page services, and  `limit`
            #    with limit/offset services
            # starting_offset - This is the offset we should use for the first page of results.
            #    generally for regualar limit/offset paging, this will be 0, and for page per_page
            #    paging it will be 1

            paging = {
                'limit': kwargs['limit'],
                'offset': kwargs['starting_offset'],
            }
            limit_field = kwargs['limit_field']
            offset_field = kwargs['offset_field']
            if not kwargs.get('args'):
                kwargs['args'] = {}

            kwargs['args'][limit_field] = paging['limit']
            kwargs['args'][offset_field] = paging['offset']

        def collect_data(resp):
            """Middleware to handle deferred from callback"""
            resp = self.transform_paged_response(resp)
            data = self.extract_data_array(resp, data_name=kwargs["data_name"])
            return defer.maybeDeferred(callback, data).addCallback(lambda ign: resp)

        # Note the use of path at first, then full_url in subsequent iterations.
        def pager(resp):
            """Continue paging through response"""
            data = self.extract_data_array(resp, data_name=kwargs["data_name"])
            if stopback() or len(data) == 0:
                return


            if use_limit_offset_paging:
                paging['offset'] +=  kwargs['offset_increase']
                kwargs['args'][offset_field] = paging['offset']
                return self.request(path=path, **kwargs).addCallback(collect_data).addCallback(pager)
            elif 'response_paging_token_field' in kwargs and 'request_paging_token_field' in kwargs:
                paging_token = resp.get(kwargs['response_paging_token_field'])
                if paging_token:
                    request_paging_token_field = kwargs['request_paging_token_field']
                    if not kwargs.get('args'):
                        kwargs['args'] = {}
                    kwargs['args'][request_paging_token_field] = paging_token
                    return self.request(path=path, **kwargs).addCallback(collect_data).addCallback(pager)
                else:
                    return
            elif 'paging' in kwargs:
                url = resp.get(kwargs['paging'], {}).get(kwargs['direction'], None)
            else:
                url = resp.get(kwargs['direction'], None)
            if url:
                authed_url = self.get_authorized_full_url(url, **kwargs)
                return self.request(full_url=authed_url, **kwargs).addCallback(collect_data).addCallback(pager)

        return self.request(path=path, **kwargs).addCallback(collect_data).addCallback(pager)

    def get_authorized_full_url(self, url, **kwargs):
        """Take a fully qualified url without oauth parameters and return the same url with the relevant
        auth parameters appended"""

        # for most services, the url will already be authorized, so just use that by default
        return url

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        msg = 'Unknown response'
        retry_at = int(time.time() + (60*60))

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]
        self.raise_error(msg, retry_at)

    def raise_error(self, msg, retry_at):
        """Raise appropriate error from service given message and retry_at"""
        if msg is Error.RATE_LIMITED:
            raise RateLimitError(msg, retry_at=retry_at, service=self.name)
        elif msg is Error.INSUFFICIENT_PERMISSIONS:
            raise InsufficientPermissionsError(msg, service=self.name)
        elif msg is Error.INVALID_REDIRECT:
            raise InvalidRedirectError(msg, service=self.name)
        elif msg is Error.INVALID_TOKEN:
            raise InvalidTokenError(msg, service=self.name)
        elif msg is Error.OVER_CAPACITY:
            raise OverCapacityError(msg, service=self.name)
        elif msg is Error.REFRESH_TOKEN:
            raise RefreshTokenError(msg, service=self.name)
        else:
            raise ServiceError(msg, service=self.name)

    def present_value(self, method_name, **kwargs):
        'Do the work for a present-value method'

        def handle_data(data):
            if len(data) <= 0:
                if kwargs.get('key_name'):
                    return {kwargs['key_name']: None}
                return

            datum = data[0]

            if kwargs.get('key_name'):
                ret = {kwargs['key_name']: datum}
            else:
                # TODO (ray): Tone this exception down once we figure out the
                # root of the problem.
                try:
                    if datum:
                        ret = json.loads(datum)
                    else:
                        return
                except:
                    raise Exception(
                        "(Bad value): %s (Method): %s (Args): %s" % (
                            data, method_name, kwargs
                        )
                    )

            if len(data) > 1:
                ret['expired_on'] = data[1]

            return ret

        return self.datastore.get_value(
            authorization=kwargs['authorization'],
            method=method_name,
        ).addCallback(handle_data)

    def interval_value(self, method_name, key_name, **kwargs):
        'Do the work for a interval-value method'
        self.ensure_arguments(['start', 'end'], kwargs.get('arguments', {}))

        def handle_data(data):
            ret = []
            for val in data:
                item = {'timestamp': val[0], key_name: val[1]}
                if len(val) > 2:
                    item['expired_on'] = val[2]
                ret.append(item)
            return {'data': ret}

        return self.datastore.get_value_range(
            authorization=kwargs['authorization'],
            method=method_name,
            start=kwargs['arguments']['start'],
            end=kwargs['arguments']['end'],
        ).addCallback(handle_data)

    def granular_value(self, method_name, key_name, **kwargs):
        'Do the work for a granular-value method'
        self.ensure_arguments(['start', 'end'], kwargs.get('arguments', {}))

        def handle_data(data):
            if not data:
                return None

            def add_num(profile):
                profile['num'] = data['num']
                return profile

            return self.profile(
                path=data['actor_id'], **kwargs
            ).addCallback(add_num)

        return self.datastore.retrieve_granular_data(
            uuid=kwargs['authorization'].uuid,
            method=key_name,
            start=kwargs['arguments']['start'],
            end=kwargs['arguments']['end'],
            user_id=kwargs['authorization'].user_id,
        ).addCallback(handle_data)


class ServiceOAuth1(Service):
    "Base class for Services that use an OAuth v1 authorization process"
    def request(self, **kwargs):
        """Make a request against the API.
        OAuth1 APIs require that we pass along OAuth details on every request.
        """
        # Either we are passed authorization as an object or we're passed
        # token/secret
        if kwargs.get('authorization'):
            token = oauth2.Token(
                key=kwargs['authorization'].token,
                secret=kwargs['authorization'].secret,
            )
        # This path is from finish_authorization()
        elif kwargs.get('token') and kwargs.get('secret'):
            token = oauth2.Token(
                key=kwargs['token'],
                secret=kwargs['secret'],
            )
            if kwargs.get('verifier'):
                token.set_verifier(kwargs['verifier'])
        # This path is from start_authorization()
        else:
            token = None

        consumer = oauth2.Consumer(
            key=self.app_info[self.environment]['app_id'],
            secret=self.app_info[self.environment]['app_secret'],
        )

        signer = oauth2.Signer(token=token, consumer=consumer)

        if kwargs.get('full_url'):
            url = kwargs['full_url']
        else:
            url = '%s/%s' % (self.endpoint_url, kwargs['path'])

        (method, uri, headers, body) = signer.create_request(
            uri=url,
            method=kwargs.get('method', 'GET'),
            headers=kwargs.get('headers'),
            body=kwargs.get('body', ''),
            parameters=kwargs.get('args'),
        )
        headers['X-Li-Format'] = ['json']

        kwargs['method'] = method
        kwargs['url'] = uri
        kwargs['headers'] = headers
        kwargs['body'] = body

        return super(ServiceOAuth1, self).request(**kwargs)


class ServiceOAuth2(Service):
    "Base class for Services that use an OAuth v2 authorization process"
    token_param = 'access_token'  # Default for most services except Foursquare.

    def request(self, **kwargs):
        if kwargs.get('authorization'):
            token = kwargs['authorization'].token
        # This path can happen if we call a method from finish_authorization()
        elif kwargs.get('token'):
            token = kwargs['token']
        else:
            token = None

        if token:
            if kwargs.get('args'):
                kwargs['args'][self.token_param] = token
            else:
                kwargs['args'] = {self.token_param: token}

            if kwargs.get('headers'):
                kwargs['headers']['Authorization'] = ['Bearer %s' % token]
            else:
                kwargs['headers'] = {'Authorization': ['Bearer %s' % token]}

        url = self.full_url(**kwargs)
        return super(ServiceOAuth2, self).request(url=url, **kwargs)


def daemon_class(cls):
    "This must be put on all daemon classes"
    cls._recurring = {
        name: method.__doc__
        for name, method in getmembers(cls)
        if hasattr(method, 'recurring')
    }
    return cls


def recurring(func):
    """
    Marks the method's 'recurring' attribute as True. Used with @daemon_class.
    """
    func.recurring = True
    return func


class Daemon(object):
    """
    All daemons will inherit from this class. It provides the functionality
    needed to make daemons work properly.
    """

    queue = 'Service'
    _delay = timedelta(minutes=15)

    def recurring(cls):
        """
        Returns the list of methods that are marked as @recurring, along with
        their docstring.
        """
        return cls._recurring

    @classmethod
    @defer.inlineCallbacks
    def perform(cls, config, uuid, method):
        """Perform a queued job from pyres.

        This method instantiates the daemon for the correct service, then
        calls run() to gather all the data for the specified uuid and method
        and store the result in the database.

        Args:
            config: A dict containing the config for Lightning.
            uuid: A string containing the uuid of the Authorization to perform.
            method: A string containing the daemon method to perform.
        """
        service = cls(
            datastore=cls.datastore,
            config={
                'environment': config['environment'],
            },
        )
        if (cls.record or cls.play):
            recorder.wrap(service.actually_request)

        authorization = None
        try:
            authorization = yield Authz(
                uuid=uuid,
            ).get_token(cls.datastore)
        except Exception as exc:
            logging.error("Error retrieving auth: %s" % exc.message)
        if authorization:
            logging.info(daemon_log(service.name, uuid, method, "Have authorization"))
            try:
                logging.info(daemon_log(service.name, uuid, method, "Running worker"))
                skip_enqueue = False
                result = yield service.run(
                    authorization=authorization,
                    daemon_method=method,
                    timestamp=int(time.time()),
                )
            except RateLimitError as exc:
                logging.error(daemon_log(service.name, uuid, method, "Rate limited - enqueue at %s" % exc.retry_at))
                skip_enqueue = True  # Don't enqueue twice.
                yield cls.enqueue(config, uuid, method, datetime.fromtimestamp(exc.retry_at))
            except InvalidTokenError as exc:
                logging.error(daemon_log(service.name, uuid, method, "Invalid token - expiring auth"))
                yield service.datastore.expire_oauth_token(
                    timestamp=int(time.time()),
                    uuid=uuid,
                )
                skip_enqueue = True  # Don't re-enqueue expired tokens.
            except LightningError as exc:
                logging.error(daemon_log(service.name, uuid, method, "Lightning Error: %s" % exc.message))
            except SQLError as exc:
                logging.error(daemon_log(service.name, uuid, method, "SQL Error: %s" % exc.message))
            except Exception as exc:
                import traceback
                logging.error(daemon_log(service.name, uuid, method, "Unhandled Exception: %s" % exc.message))
                logging.error(traceback.format_exc())
            finally:
                if not skip_enqueue:
                    try:
                        enqueue_time = datetime.now() + getattr(service, method).enqueue_delta
                    except:
                        enqueue_time = None
                    logging.info(daemon_log(service.name, uuid, method, "Enqueueing"))
                    yield cls.enqueue(config, uuid, method, enqueue_time)

        else:
            logging.info(daemon_log(service.name, uuid, method, "No authorization found"))

    @classmethod
    @newrelic.agent.background_task()
    def enqueue(cls, config, uuid, method, datetime=None):
        'Enqueue a scheduled entry into pyres'
        if datetime is None:
            datetime = cls.delayed_datetime()

        return cls.resq.enqueue_at(datetime, cls, config, uuid, method)

    @classmethod
    def delayed_datetime(cls):
        'Overridable method to determine how long to wait for the job'
        return datetime.now() + cls._delay

    @newrelic.agent.background_task()
    @defer.inlineCallbacks
    def run(self, **kwargs):
        """
        Call all the API methods on this service, aggregating their response,
        then write it out to the database.

        This is a sergeant method around:
        * Gather the methods to work over
          * Must conform to the recurring() snapsho() signature
        * serialize_value(method, value) - serializes a single datum
          * must -not- be @defer.inlineCallbacks
        * write_datum() - writes the data to the datastore
          * expects 'authorization'
          * expects 'timestamp'
          * must return a deferred

        The child class is expected to override serialize_value().
        """
        assert kwargs.get('authorization') is not None
        assert kwargs.get('timestamp') is not None
        assert kwargs.get('daemon_method') is not None

        # This could be rewritten using defer.gatherResults()
        uuid = kwargs['authorization'].uuid
        method = kwargs['daemon_method']
        try:
            logging.info(daemon_log(self.name, uuid, method, "Attempting %s" % method))
            data = yield getattr(self, method)(**kwargs)
        except LightningError as exc:
            logging.error(daemon_log(self.name, uuid, method, "%s received %s" % (method, exc.message)))
            raise exc
        except SQLError as exc:
            logging.error(daemon_log(self.name, uuid, method, "%s received SQL Error %s" % (method, exc.message)))
            raise exc

        if data or (data == 0):
            logging.info(daemon_log(self.name, uuid, method, "Received data for %s" % method))
            yield self.write_datum(
                method=method,
                data=self.serialize_value(method, data),
                feed_type=method,
                **kwargs
            )
        else:
            # This could be because the method writes data itself.
            logging.info(daemon_log(self.name, uuid, method, "No data for %s" % method))

    def serialize_value(self, method, value):
        """Serialize the value returned by a method before we store it.
        Most services will override this basic implementation.
        """
        if method in ['profile']:
            return json.dumps(value)
        return value['num']

    def write_datum(self, **kwargs):
        """
        Write the data to the datastore.
        This must return a Deferred so that others can yield on it.
        """
        return self.datastore.write_value(
            uuid=kwargs['authorization'].uuid,
            timestamp=kwargs['timestamp'],
            method=kwargs['method'],
            data=kwargs['data'],
            feed_type=kwargs.get('feed_type'),
        )

def service_class(cls):
    """
    Sets the _methods attribute on the class to a dict with keys being methods
    that have the @api_method decorator and values being those methods'
    docstrings.
    """
    cls._methods = {
        'GET': {},
        'POST': {},
    }
    for name, method in getmembers(cls):
        if hasattr(method, 'api'):
            cls._methods[method.api][name] = method.__doc__
    cls._writable = {}
    return cls


# Decorators that take arguments return a real decorator that doesn't take
# arguments. It's all very meta.
def api_method(method):
    "Marks the method's 'api' attribute as <method>. Used with @service_class"
    def real_decorator(func):
        func.api = method
        return func
    return real_decorator

def check_account_created_timestamp(func):
    """Check the datastore for the account_created_timestamp in the authorization.
    If the model doesn't have a timestamp, call the method and store the result.
    """

    @wraps(func)
    @defer.inlineCallbacks
    def real_decorator(*args, **kwargs):
        if kwargs['authorization'].account_created_timestamp:
            defer.returnValue({
                'timestamp': kwargs['authorization'].account_created_timestamp
            })
        else:
            resp = yield func(*args, **kwargs)
            kwargs['authorization'].account_created_timestamp = resp['timestamp']
            yield kwargs['authorization'].save()
            defer.returnValue(resp)

    return real_decorator

def enqueue_delta(**time_delta):
    """Marks the method's 'enqueue_delta' attribute as a timedelta which will be
    used to calculate the method's next enqueue time in perform().

    Any valid timedelta constructor kwargs may be used ranging from seconds
    to days.

    Usage:
    @enqueue_delta(minutes=5)
    def foo(self, bar):
    """
    def real_decorator(func):
        func.enqueue_delta = timedelta(**time_delta)
        return func
    return real_decorator


class Web(object):
    "This is the baseclass for all web-facing service objects"
    def get_feed_args(self, **kwargs):
        'Default version of getting the feed args.'
        return {}

    def get_feed(self, **kwargs):
        'Generic method to iterate over the feed for N results.'
        if not 'stream_type' in kwargs:
            kwargs['stream_type'] = None
        posts = []
        limit = kwargs.get('num', 20)

        if kwargs.get('method'):
            method = kwargs['method']
            del(kwargs['method'])
        else:
            method = 'parse_post'

        def add_post(data):

            def_list = []

            def parse_data(data):
                """ Do some post proccessing on the list of posts we got back from the external
                api.  Take a list of posts, `data` an for each post do the following:
                  * Exclude it if it is private and the client hasn't requested to see private posts
                  * Exclude it if it is outside the range the user requested
                  * Add the `is_echo` parameter to the post's metadata, by comparing user_ids
                  * Exclude the post if it is an 'echo' post and the client not requested to see echo
                  * Exclude the post if it doesn't match the requested stream filter

                  Args:
                     * `data` - A list a posts parsed into standard LG format
                   Yields:
                      * A list of posts with 'echo' field added, filtered based on feed paramters"""

                for proto in data:
                    proto = proto[1]
                    if proto:
                        is_hidden = kwargs['show_private'] < proto['metadata']['is_private']
                        # Filter out any posts not in our range

                        # WordPress and Runkeeper don't pay attention to the time components
                        # of datetimes.  This means that sometimes we'll get results for a
                        # specified time range that are actually outside of that time range.
                        # Thus, we filter them out manually here.  In at least the WordPress
                        # case this makes new items appear dealyed, when looking at the backward
                        # facing timeline for the curent time.  In this case an item posted today
                        # would show up in wordpress as *after* the current date, but this filter
                        # would filter that item out. Its not a perfect solution, but currently
                        # its the best option we have.

                        req_timestamp = kwargs.get('timestamp', 0)
                        is_out_of_range = 0
                        should_include_post = True
                        if hasattr(self, 'should_include_post'):
                            should_include_post = self.should_include_post(proto, **kwargs)

                        if req_timestamp:
                            post_timestamp = proto.get('metadata', {}).get('timestamp', 0)
                            is_forward = kwargs.get('forward', 0)
                            if is_forward and req_timestamp > post_timestamp:
                                is_out_of_range = 1
                            elif not is_forward and req_timestamp < post_timestamp:
                                is_out_of_range = 1

                        if is_hidden or is_out_of_range == 1 or not should_include_post or len(posts) == limit:
                            continue
                        proto['metadata']['service'] = self.name
                        if str(kwargs['authorization'].user_id) == str(proto['author']['user_id']):
                            proto['metadata']['is_echo'] = 0
                        else:
                            proto['metadata']['is_echo'] = 1

                        if kwargs['echo'] >= proto['metadata']['is_echo']:
                            posts.append(proto)
                return posts

            for post in data:
                def_list.append(defer.maybeDeferred(getattr(self, method), post, **kwargs))
            return defer.DeferredList(def_list).addCallback(parse_data)

        def at_limit():
            return len(posts) >= limit

        def return_posts(ign):
            return posts

        # Here we have kwargs['show_private'] = 0/1

        kwargs['args'] = kwargs.get('args', {})
        # Always make requests for 50 items, even if we use less
        kwargs['args'].update(self.get_feed_limit(50))
        kwargs['args'].update(self.get_feed_timestamp(**kwargs))
        kwargs['args'].update(self.get_feed_args(**kwargs))

        # Default the path to the feed_url. This allows overriding in children.
        if kwargs.get('path'):
            path = defer.succeed(kwargs['path'])
            del(kwargs['path'])
        else:
            path = defer.maybeDeferred(self.get_feed_url, **kwargs)

        def make_request(path):
            if not kwargs.get('stopback'):
                kwargs['stopback'] = at_limit
            else:
                original_stopback = kwargs['stopback']
                kwargs['stopback'] = lambda: at_limit() or original_stopback()

            return self.request_with_paging(
                path=path,
                callback=add_post,
                **kwargs
            ).addCallback(return_posts)

        return path.addCallback(make_request)

    @api_method('GET')
    def most_recent_activity(self, echo=0, **kwargs):
        "The most recent activity on this service's feed"
        def get_first(result):
            if result and len(result):
                return result[0]
            # TODO: Abstract this out into a "default base post"
            return {
                'service': self.name,
                'metadata': {
                    'post_id': 0,
                    'timestamp': 0,
                    'is_private': 1,
                    'service': self.name,
                },
                'author': {
                    'user_id': 0,
                    'timestamp': 0,
                    'picture_url': '',
                    'profile_url': '',
                },
                'activity': {
                    'text': '',
                },
            }

        return self.get_feed(
            num=1,
            echo=echo,
            show_private=kwargs['arguments'].get('show_private', 0),
            stream_type=None,
            **kwargs
        ).addCallback(get_first)

    def current_timestamp(self):
        """overridable method to get the current timestamp"""
        return int(time.time())

    @check_account_created_timestamp
    @defer.inlineCallbacks
    def account_created_timestamp(self, high_start=None, low_start=None,
        limit=1, **kwargs):
        """Returns the approximate (to within a month) time at which the user
        first posted to this service
        """
        # In this generic implemetation, we do a binary search on the stream to
        # get within a month of the actual time

        assert low_start

        low = low_start
        high = high_start or self.current_timestamp()
        threshold = 31 * 24 * 60 * 60  # Seconds in a month

        def extract_timestamp(items):
            try:
                timestamp = items[0]['metadata']['timestamp']
            except:
                timestamp = None

            return timestamp
        def stopback():
            # Force get_feed to stop after it gets one page of results, since
            # we don't care about the other pages.
            return True

        def next_lower_timestamp(guess):
            """query the service to see if there is a timestamp lower than
            `guess` if there is one, return it.

            Otherwise, return None
            """

            return self.get_feed(
                num=limit, forward=0, timestamp=guess, show_private=1, echo=0,
                stopback=stopback, **kwargs
            ).addCallback(extract_timestamp)

        # Ensure they have at least one item in the given range.
        # If they don't, we don't have enough information to continue.
        first_lower = yield next_lower_timestamp(high)
        if first_lower:
            while (high - low) > threshold:
                guess = (low + high) // 2
                next_lower = yield next_lower_timestamp(guess)
                # do we have anything older than guess?
                if next_lower:
                    # yes, guess was too high - so use the guess as the new high
                    high = guess

                else:
                    # no
                    low = guess
            best_guess = (low + high) // 2
        else:
            best_guess = None

        defer.returnValue({'timestamp': best_guess})

    @classmethod
    def api_method(cls, method_name, key_name=None,
            present=None, interval=None,
            delegate_to=None, delegate_key=None):
        """Builds API methods for use with the Web interface. This will build
        methods that wrap present_value (and, if specified, interval_value).

        The optional key_name will specify the key to use when returning the
        data.

        The optional delegate_to/delegate_key combination will specify what
        method to delegate to (instead of method_name) and what key in that
        hash to pull back.
        """
        if not present:
            raise ApiMethodError("Must specify 'present' docstring")

        if hasattr(cls, method_name):
            raise ApiMethodError('%s has already been built' % method_name)

        if delegate_to:
            if not delegate_key:
                raise ApiMethodError(
                    'Must specify delegate_key with delegate_to'
                )

            @defer.inlineCallbacks
            def _call(self, **kwargs):
                ret = yield self.present_value(
                    method_name=delegate_to, **kwargs
                )
                if ret is None:
                    defer.returnValue(ret)
                defer.returnValue({key_name: ret.get(delegate_key, None)})
        else:
            def _call(self, **kwargs):
                return self.present_value(
                    method_name=method_name, key_name=key_name, **kwargs
                )

        _call.api = 'GET'
        _call.__doc__ = present
        setattr(cls, method_name, _call)
        cls._methods['GET'][method_name] = present
        cls._writable[method_name] = key_name

        if interval:
            interval_method_name = method_name + '_interval'
            if hasattr(cls, interval_method_name):
                raise ApiMethodError(
                    '%s has already been built' % interval_method_name
                )
            if delegate_to or delegate_key:
                raise ApiMethodError(
                    'Cannot use interval with delegate_to/delegate_key'
                )

            def _call(self, **kwargs):
                return self.interval_value(
                    method_name=method_name, key_name=key_name, **kwargs
                )

            _call.api = 'GET'
            _call.__doc__ = interval
            setattr(cls, interval_method_name, _call)
            cls._methods['GET'][interval_method_name] = interval

    @classmethod
    def granular_method(cls, method_name, key_name, docstring):
        """Builds API methods for use with the Web interface. This will build
        methods that wrap granular_value"""
        if not docstring:
            raise ApiMethodError("Must specify 'present' docstring")

        if hasattr(cls, method_name):
            raise ApiMethodError('%s has already been built' % method_name)

        def _call(self, **kwargs):
            return self.granular_value(
                method_name=method_name, key_name=key_name, **kwargs
            )

        _call.api = 'GET'
        _call.__doc__ = docstring
        setattr(cls, method_name, _call)
        cls._methods['GET'][method_name] = docstring
        cls._writable[method_name] = key_name

    def methods(self):
        """
        Returns the list of methods that are marked as @api_method, along with
        their docstring. This can also be setup via the api_method classmethod.
        """
        return self._methods

    def daemon_object(self):
        'Returns an instance of the daemon_class, properly instantiated'
        daemon_class = self.daemon_class
        return daemon_class(
            datastore=self.datastore,
            config={
                'environment': self.environment,
            },
        )

    def construct_authorization_url(self, **kwargs):
        """Constructs the redirect_uri for start_authorization().
        Assumptions:
            self.permissions has been set appropriately.
            Caller has already ensured kwargs['args'] contains:
                redirect_uri.
                Any other values needed.
        Arguments:
            client_name.
            base_uri.
        """
        assert kwargs['client_name'] is not None
        assert kwargs['base_uri'] is not None

        url = urlsplit(kwargs['base_uri'])
        query_string = parse_qs(url.query)

        # Add optional permission requirements
        if hasattr(self, 'permissions'):
            query_string.update(self.permissions.get(kwargs['client_name'], {}))

        # Add service-specific values last, so they override everything else.
        query_string.update(kwargs.get('args', {}))

        return urlunsplit([
            url.scheme, url.netloc, url.path,
            # The docs for both parse_qs and urlencode fail to mention that the
            # second parameter is required for true reversability. This is
            # documented in http://bugs.python.org/issue15593
            urlencode(query_string, doseq=True),
            url.fragment
        ])

    def start_authorization(self, client_name, args):
        "Abstract base method for start_authorization"
        raise NotImplementedError

    def finish_authorization(self, client_name, args):
        "Abstract base method for finish_authorization"
        raise NotImplementedError

    def revoke_authorization(self, authorization):
        "Abstract base method for revoke_authorization"
        return defer.succeed(True)

    def service_revoke_authorization(self, client_name, args):
        "Asynchronously revoke authoriation. This is unimplemented."
        raise NotImplementedError

    def write_new_value(self, **kwargs):
        'Write new value to the datastore'
        kwargs['uuid'] = kwargs['authorization'].uuid
        if self._writable.get(kwargs['method']):
            kwargs['data'] = kwargs['data'][self._writable[kwargs['method']]]
        else:
            kwargs['data'] = json.dumps(kwargs['data'])

        return self.datastore.write_value(**kwargs)

class StreamCachedService:
    def get_feed(self, **kwargs):
        'Generic method to iterate over the stream cachce for `num` results.'
        if not 'stream_type' in kwargs:
            kwargs['stream_type'] = None
        posts = []
        limit = kwargs.get('num', 20)

        def add_post(data):
            # What if the user doesn't have anything in the stream
            if not data:
                return

            for post in data:
                proto = post['data']
                if proto:
                    if kwargs['show_private'] < proto['metadata']['is_private']:
                        continue

                    proto['metadata']['service'] = self.name
                    if str(kwargs['authorization'].user_id) == str(proto['author']['user_id']):
                        proto['metadata']['is_echo'] = 0
                    else:
                        proto['metadata']['is_echo'] = 1

                    if kwargs['echo'] >= proto['metadata']['is_echo']:
                        posts.append(proto)

        def return_posts(ign):
            return posts

        args = {
            'uuid': kwargs['authorization'].uuid,
            'limit': limit,
            'stream_type': kwargs['stream_type']
        }

        # most_recent_activity doesn't provide a timestamp
        if kwargs.get('timestamp'):
            if kwargs.get('forward'):
                args['start'] = kwargs['timestamp']
            else:
                args['end'] = kwargs['timestamp']
        return self.datastore.retrieve_stream_cache(
            **args
        ).addCallback(add_post).addCallback(return_posts)


    def parse_and_save_paged_stream(self, save_callback=None, **kwargs):
        """iterate over all the items in the stream, and update the stream chache using that agregated data"""
        all_data = []

        def save_items(_):
            if save_callback:
                save_callback(all_data)
            else:
                return self.parse_and_save_stream_data(all_data, **kwargs)

        def aggregate(page_data_items):
            all_data.extend(page_data_items)

        return self.request_with_paging(
            callback=aggregate,
            **kwargs).addCallback(save_items).addCallback(lambda _: None)



    def parse_and_save_stream_data(self, data, parse_method='parse_post', **kwargs):
        """Take the sercive specific steram items stored in the data array, parse them into
        LG's format via `parse_method`, and save them to the db"""

        def add_posts(parsed_posts):
            entries = []

            # setup the fields to save
            for parsed_post in parsed_posts:
                if not parsed_post:
                    continue
                entry = {}
                entry['data'] = parsed_post
                entry['item_id'] = entry['data']['metadata']['post_id']
                entry['timestamp'] = entry['data']['metadata']['timestamp']
                entries.append(entry)

            # save them
            return self.datastore.update_stream_cache(
                entries,
                kwargs['authorization'],
            )

        return defer.maybeDeferred(self.parse_posts, data, parse_method=parse_method, **kwargs).addCallback(add_posts)


    def parse_posts(self, entry_list, parse_method='parse_post', **kwargs):
        """ Take a list of entries from the 3rd party APIs activiy feed, and convert it into a list of LG
        formatted posts for the stream.

        This version works well when there is a 1-to-1 mapping between entries and posts.  If more than one LG
        stream post will be generated per entry, this method should be overridden in the subclass

        Args:
           entry_list - a list unparsed entries from the 3rd party API's endpoint
           parse_method - the method that takes a post to parse, and parses into LG stream format
           kwargs - other arguments to be passed along to the method that does the actual parsing

        Yields a deferred list of posts in the propper LG stream format."""

        return defer.gatherResults([
                defer.maybeDeferred(getattr(self, parse_method), entry, **kwargs) for entry in entry_list
        ])

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the time at which the user first posted to to this serivice"""

        def return_timestamp(items):
            try:
                timestamp = items[0]['data']['metadata']['timestamp']
            except:
                timestamp = None
            return {'timestamp': timestamp}

        uuid = kwargs['authorization'].uuid
        return self.datastore.retrieve_stream_cache(
            order_by='timestamp ASC',
            limit=1,
            uuid=uuid,
            **kwargs
        ).addCallback(return_timestamp)


class GoogleService(ServiceOAuth2):
    """Base class for Google-based services"""

    def request(self, **kwargs):
        if not kwargs.get('args'):
            kwargs['args'] = {}

        kwargs['args']['alt'] = 'json'  # Response format
        kwargs['args']['v'] = 2  # Every request is versioned.

        return super(GoogleService, self).request(**kwargs)

    def request_with_paging(self, path, callback, **kwargs):
        """Blogger & Google+ use page tokens for results, so we need to grab those and pass them
        along when possible. Note that youtube uses different paging

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method

        Yields: A deferred request which when completed will have called each page of results with `callback`"""


        return super(GoogleService, self).request_with_paging(
            path, callback,
            response_paging_token_field='nextPageToken',
            request_paging_token_field='pageToken',
            data_name='items',
            **kwargs
        )

    def start_authorization(self, **kwargs):
        """Get the authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], kwargs.get('args', {}))

            kwargs['args']['client_id'] = self.app_info[self.environment]['app_id']
            kwargs['args']['response_type'] = 'code'
            kwargs['args']['access_type'] = 'offline'
            kwargs['args']['approval_prompt'] = 'force'
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        return defer.succeed(
            self.construct_authorization_url(
                base_uri=self.auth_url, **kwargs
            )
        )

    @defer.inlineCallbacks
    def refresh_token(self, **kwargs):
        arguments = {
            'client_id': self.app_info[self.environment]['app_id'],
            'client_secret': self.app_info[self.environment]['app_secret'],
            'refresh_token': kwargs['authorization'].refresh_token,
            'grant_type': 'refresh_token',
        }
        resp = yield self.actually_request(
            url=self.access_token_url,
            postdata=urlencode(arguments),
            method='POST',
        )

        response = json.loads(resp.body)
        kwargs['authorization'].token = response['access_token']
        yield kwargs['authorization'].save()

        token = kwargs['authorization'].token
        kwargs['args'][self.token_param] = token
        kwargs['headers']['Authorization'] = ['Bearer %s' % token]
        del kwargs['url']

        defer.returnValue(kwargs)


class OAuth2CSRFChecker:
    "Tools to allow the use of the 'state' parameter to avoid CSRF attacks"
    def generate_random_string(self):
        return get_uuid()

    @defer.inlineCallbacks
    def generate_state_token(self):
        state = self.generate_random_string()
        yield self.datastore.store_inflight_authz(
            service_name=self.name,
            state=state,
        )
        defer.returnValue(state)

    @defer.inlineCallbacks
    def check_state_token(self, state):
        inflight_authz = yield self.datastore.retrieve_inflight_authz(
            service_name=self.name,
            state=state,
        )
        if not inflight_authz:
            raise DatastoreError('No inflight_authz for %s: %s' % (self.name, state))


class MultiEndPointFeedService(Web):
    """ Provides functionality for a service that needs to get Feed/Stream data from
    multiple URLs.  The child class must implement `feed_endpoint_parsing_methods()`
    which maps each endpoint url to a method for parsing that sort of post.  It is
    incompatible with StreamCachedService as it expects to but pulling stream data
    directly from the endpoints given."""

    def get_feed(self, endpoint_to_parse_method={}, **kwargs):
        """
        Get feed data for multiple endpoints and braid those results together into a single stream
        """
        if not 'stream_type' in kwargs:
            kwargs['stream_type'] = None
        def merge_results(results):
            feed = []
            for result in results:
                if result[0]:
                    for item in result[1]:
                        if len(feed) < kwargs.get('num', 20):
                            feed.append(item)
            return feed

        return defer.DeferredList([
            super(MultiEndPointFeedService, self).get_feed(
                path=path, method=method, **kwargs
            ) for path, method in endpoint_to_parse_method.iteritems()
        ]).addCallback(merge_results)

class ContentAuthoredService(Web):
    """Provides common methods for services that pull back authored content in
    their stream results.
    """
    @api_method('GET')
    @defer.inlineCallbacks
    def recent_content_authored(self, echo=0, **kwargs):
        "The recent content authored by this user"
        content_authored = yield self.get_feed(
            num=5,
            echo=echo,
            show_private=kwargs['arguments'].get('show_private', 0),
            stream_type=None,
            **kwargs
        )
        defer.returnValue({"data": content_authored})

################################################################################
# These are generic utilities used only by the services
# They may better live in some service.utils class

class Profile(LimitedDict):
    """Profile class.
    Represents a user's Profile information.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'bio',
            'email',
            'first_name',
            'gender',
            'headline',
            'last_name',
            'maiden_name',
            'middle_name',
            'name',
            'profile_link',
            'profile_picture_link',
            'username',
        ]
        super(Profile, self).__init__(keys, **kwargs)


class Birth(LimitedDict):
    """Birth class.
    Represents a user's Birth information.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'age',
            'dob_day',
            'dob_month',
            'dob_year',
        ]
        super(Birth, self).__init__(keys, **kwargs)
        self['age'] = self.calculate_age()

    def calculate_age(self):
        month = self['dob_month']
        day = self['dob_day']
        year = self['dob_year']

        if not month or not day or not year:
            return None
        born = date(
            month=month,
            day=day,
            year=year,
        )
        today = date.today()
        try:
            birthday = born.replace(year=today.year)
        except ValueError:
            # Raised when birth date is February 29 and the current year is not a leap year
            birthday = born.replace(year=today.year, day=born.day-1)
        if birthday > today:
            return today.year - born.year - 1
        else:
            return today.year - born.year


class Contact(LimitedDict):
    """Contact class.
    Represents a user's Contact information
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'region',
            'city',
            'state',
            'country_code',
            'phone_numbers',
        ]
        super(Contact, self).__init__(keys, **kwargs)

class Education(LimitedDict):
    """Education class.
    Represents a user's Education position.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'degree_earned',
            'end_date_month',
            'end_date_year',
            'field_of_study',
            'school_name',
            'start_date_month',
            'start_date_year',
            'education_id',
        ]
        super(Education, self).__init__(keys, **kwargs)


class Work(LimitedDict):
    """Work class.
    Represents a user's Work position.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'city',
            'end_date_month',
            'end_date_year',
            'is_current',
            'organization_name',
            'start_date_month',
            'start_date_year',
            'state',
            'title',
            'work_id',
        ]
        super(Work, self).__init__(keys, **kwargs)
