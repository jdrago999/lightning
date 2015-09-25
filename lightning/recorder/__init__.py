from copy import copy
import json
from lightning.recorder.wraptools import wraps
from lightning.utils import get_lightning_path
import os
import pprint
import random
from twisted.internet import defer, reactor
import urllib
import urlparse


class SingletonType(type):
    """Type that ensures we have a singleton.

    Reference:
        http://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
    """
    def __call__(cls, *args, **kwargs):
        try:
            return cls.__instance
        except AttributeError:
            cls.__instance = super(SingletonType, cls).__call__(*args, **kwargs)
            return cls.__instance


class RecordedRequest(object):
    def __init__(self, url, **kwargs):
        """Class used to mock a request."""
        self.url = url


class RecordedResponse(object):
    def __init__(self, *args, **kwargs):
        """Class used to mock a response.

        Attributes:
            code: An integer representing the HTTP status code.
            headers: An array of HTTP headers.
            content_type: A string containing the response's content type.
            body: A string containing the response's body.
        """
        self.code = kwargs.get('code', 200)
        self.headers = kwargs.get('headers', [])
        self.content_type = kwargs.get('content_type', 'application/json')
        self.body = kwargs.get('body', '{}')

        # Parameters for responses from the synchronous request module
        self.code = kwargs.get('status_code', self.code)
        self.body = kwargs.get('_content', self.body)

        self.request = RecordedRequest(kwargs.get('url', None))

    def serialize(self):
        """Serialize the response.

        Returns:
            A dict with the response's attributes.
        """
        return {
            'code': self.code,
            'headers': self.headers,
            'content_type': self.content_type,
            'body': self.body,
        }

    @property
    def content(self):
        return self.body

    @property
    def cookies(self):
        return {}

    @property
    def status_code(self):
        return self.code


class RequestRecorder(object):
    """RequestRecorder singleton.

    Records responses from a request function to a JSON file, which can then
    be used to play back the responses without hitting the network.
    Borrows in concept from VCR.py, but supports twisted's deferred responses
    and stores all results in a single JSON file.

    Usage:
        from lightning.recorder import recorder

        # Overwrite the Web & Daemon actually_request functions for a service
        # in your test class's setUp method.
        recorder.wrap(ServiceWeb.actually_request)
        recorder.wrap(ServiceDaemon.actually_request)

        # To start recording
        recorder.record()

        # To stop recording
        recorder.stop()

        # To save responses to output file (in your test class's tearDown method)
        recorder.save()

    Attributes:
        _request: A request function to wrap with recording and playback functionality.
        _response: A response class to return recorded responses with.
        _input_file: A filename to load responses from (path relative to lightning directory).
        _output_file: A filename to save responses to (path relative to lightning directory).
        _record: A boolean that determines whether to record or playback responses.
        _matches: A dict containing RecordedResponses keyed by method and uri.
        use_filters: A boolean that determines whether this recording or playback should use response filters
        simulate_delays_and_errors: A boolean that determines whether filtered playback should create fake delays or errors

    Reference:
        https://github.com/kevin1024/vcrpy
    """
    __metaclass__ = SingletonType

    def __init__(self, *args, **kwargs):
        """Set up our recorder, request function, and response object."""
        if args:
            self._request = args[0]
        else:
            self._request = None
        self._debug = kwargs.get('debug', False)
        self._response = kwargs.get('response', RecordedResponse)
        self._input_file = kwargs.get('input_file', 'lightning/test/etc/recorded_response.json')
        self._output_file = kwargs.get('output_file', 'lightning/test/etc/recorded_response.json')
        self._skipped_args = kwargs.get('skipped_args', [
            'oauth_nonce',
            'oauth_signature',
            'oauth_timestamp',
            'access_token',
            'oauth_body_hash',
            'oauth_consumer_key',
            'oauth_token',
            'oauth_callback',
            # Used by LinkedIn stream
            'start',
            'before',
        ])
        self._record = False
        self.use_filters = kwargs.get('use_filters', False)
        self.simulate_delays_and_errors = kwargs.get('simulate_delays_and_errors', False)


        self._matches = self.load()
        if self._request:
            self.wrap(self._request)

    def get_skipped_args(self):
        # only ignore the 'page' attribute if we are using request filters.  For some reason some tests
        # fail on startup/teardown with unrelated database errors if 'page' is not included for unit tests

        skip = list(self._skipped_args)
        if self.use_filters:
            skip.append("page")
        return skip


    def get_response(self, method, uri, request_args):
        """Get the response from a method, uri, and any request arguments.

        Returns:
            A RecordedResponse object containing the response for the given
            method, URL, and request arguments.

        Raises:
            If no RecordedResponse is found, then a KeyError exception is raised.
        """

        # only ignore the 'page' attribute if we are using request filters.  For some reason some tests
        # fail on startup/teardown with unrelated database errors if 'page' is not included for
        skip = self.get_skipped_args()
        uri = self._strip_args(uri, skip)

        response = self._matches.get(method, {}).get(uri, None)
        if not self._record and not response:
            pprint.pprint(recorder._matches)
            raise KeyError('No response found for %s' % pprint.pformat(uri))

        # return a copy of the response.  This is important, because if we don't, modifications by response filters
        # and the like will persist accross requests
        return copy(response)

    def load(self):
        """Load RecordedResponses from an input file.

        Returns:
            A dict containing the recorded responses keyed by method and uri.
            If the input file was not found, default to record mode and return
            an empty matches hash.
        """
        result = {'GET': {}, 'POST': {}}
        if not self._record:
            try:
                input_filename = os.path.join(get_lightning_path(), self._input_file)
                with open(input_filename, 'r') as input_file:
                    result = json.load(input_file)
                    result = self._unserialize(result)
                    # print('Loaded playback file: %s' % self._input_file)
            except (IOError, ValueError) as exc:
                print('Unable to load file: %s' % (exc.message or exc[1]))
        self._matches = result
        return result

    def record(self):
        """Enable recording mode.
        Returns:
            A boolean indicating the current recording status.
        """
        self._record = True
        return self._record

    def register_uri(self, method, uri, **request_args):
        """Store uri and response.
        Returns:
            A RecordedResponse object containing the stored response.
        """

        skip = self.get_skipped_args()
        uri = self._strip_args(uri, skip)

        self._matches[method][uri] = RecordedResponse(**request_args)
        self.save()

        return self._matches[method][uri]

    def _serialize(self):
        """Serialize all RecordedResponses.
        Returns:
            A dict containing the serialized RecordedResponses.
        """
        result = {}
        for method in self._matches:
            result[method] = {}
            for uri in self._matches.get(method, {}):
                result[method][uri] = self._matches[method][uri].serialize()
        return result

    def stop(self):
        """Stop recording.

        Returns:
            A boolean indicating the current recording status.
        """
        self._record = False
        return self._record

    def play(self):
        """Playback responses.

        Returns:
            A boolean indicating the current recording status.
        """
        return self.stop()

    def _strip_args(self, uri, stripped_args):
        """Strip arguments from uri's query string.
        Args:
            uri: A string containing the URL to strip from.
            stripped_args: An array containing string arguments to strip from URL.
        Returns:
            A string containing the URL with the arguments stripped from the
            query string.

            If no query string is present, the uri is returned unchanged.
        """
        try:
            index = uri.index('?')
        except:
            return uri

        params = urlparse.parse_qs(uri[index+1:])
        for arg in stripped_args:
            if arg in params:
                del params[arg]

        q_params = []
        for k in params:
            val = params[k][0]
            if k == 'redirect_uri':
                val = urllib.quote_plus(val)

            q_params.append('%s=%s' % (k, val))

        querystring = '&'.join(q_params)

        if querystring:
            querystring = '?%s' % querystring

        stripped_uri = '%s%s' % (uri.split('?')[0], querystring)
        return stripped_uri

    def _unserialize(self, data):
        """Unserialize all recorded responses in _matches dict.

        Args:
            data: dict that needs to be unserialized.

        Returns:
            A dict containing the loaded RecordedResponses.
        """
        result = {}
        for method in data:
            result[method] = {}
            for uri in data.get(method, {}):
                resp = data[method][uri]
                rec_resp = RecordedResponse(
                    code=resp['code'],
                    headers=resp['headers'],
                    content_type=resp['content_type'],
                    body=resp['body'],
                    url=uri,
                )
                result[method][uri] = rec_resp
        return result

    def wrap(self, request):
        """Wrap a request function with recording and playback functionality.
        Args:
            request: A request function to wrap with recording and playback.
        Returns:
            A reference to the recorder.
        """
        if not self._request:
            self._request = request
        recorder = self

        @wraps(request)
        def request_with_recording(req, self, *args, **kwargs):
            """Wrapper around request to add recording and playback."""
            synchronous = False
            try:
                url = kwargs.get('url') or args[0]
                method = kwargs['method']
            except KeyError:
                synchronous = True
                method = self.upper()
                url = args[0]
                args = (method, url)

            if recorder._record:
                def save_response(response):
                    """Save our live response."""
                    recorder.register_uri(method, url, **vars(response))
                    return defer.succeed(response)
                print('Recording response for %s' % pprint.pformat(url))
                if synchronous:
                    resp = req(*args, **kwargs)
                    recorder.register_uri(method, url, **vars(resp))
                    return resp
                else:
                    return req(*args, **kwargs).addCallback(save_response)
            else:
                resp = recorder.get_response(method, url, kwargs)

                delay = 0
                if hasattr(self, 'response_filter') and recorder.use_filters:
                    kwargs['url'] = url


                    # apply any relevant response filters if the object we're wrapping suports them:
                    resp = self.response_filter.filter(kwargs, resp)

                    if not recorder.simulate_delays_and_errors:
                        if synchronous:
                            return resp
                        else:
                            return defer.succeed(resp)
                    else:

                        # delay the request for a reasonable amount of time.  Use a random number on a
                        # normal distribution and use 0 if we get any negatvie values
                        delay = random.normalvariate(1.5, 1.0)
                        if delay < 0:
                            delay = 0

                        resp = self.response_filter.error_filter(resp, 0.03, self.status_errors.keys())

                # return the response, but only after possibly waiting for a delay
                def return_response(_):
                    # We're overriding actually_request here, but its important if we're sending error
                    # responses, so add it back here
                    if resp.code not in [200, 201]:
                        self.parse_error(
                            resp.code,
                            resp.request.url,
                            resp.headers,
                            resp.body
                        )

                    # Okay, no errors, return the response as is
                    return resp

                if synchronous:
                    # don't worry about doing a delay if we're in synchronous mode, since synchronous mode is
                    # only used for unit tests which don't need delays
                    return resp
                else:
                    if delay:
                        d = defer.Deferred()
                        d.addCallback(return_response)
                        reactor.callLater(delay, d.callback, None)
                        return d
                    else:
                        # Strange things can happen if the delay is 0, so in this case, just call return_response
                        # directly.  If we don't do this, the random numbers generated in response filters can be
                        # sort of 'duplicated' due to the wierdness with the low level ordering of deferreds.
                        return defer.succeed(return_response(None))


        return self

    def save(self):
        """Save our recorded responses to a file.

        Returns:
            A boolean indicating if responses were saved or not.

            Responses will only be saved if record mode is enabled.
        """

        if self._record:
            output_filename = os.path.join(get_lightning_path(), self._output_file)
            dirname, filename = os.path.split(output_filename)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(output_filename, 'w') as output_file:
                output_file.write(json.dumps(self._serialize(), indent=2, sort_keys=True))
                return True
        return False


recorder = RequestRecorder()
