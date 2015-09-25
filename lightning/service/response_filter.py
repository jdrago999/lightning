from __future__ import absolute_import

import json
import re
from urlparse import urlparse
import random
import string
from datetime import datetime
import time

from pprint import pprint


def response_filter(path=None, parse_json=True):

    def decorator(func):
        func.response_filter = {
            'path': path,
            'parse_json': parse_json,
            'func': func,
        }
        return func
    return decorator


class ResponseFilter(object):
    filter_registry = {}

    def fake_timestamp(self):
        "generate a fake timestamp in the last six months"
        latest_timestamp = int(time.time())
        earliest_timestamp = latest_timestamp - (6 * 30 * 24 * 60 * 60)
        return random.randint(earliest_timestamp, latest_timestamp)

    def fake_hex_string(self, length):
        """generate a random hexidecimal string to use as a access_token."""
        return "".join( [random.choice(string.letters[:6] + string.digits) for i in xrange(int(length))] )


    def fake_word(self):
        "return a randomly genreated word with the lenth that is random, but in the distribution of english words"
        avg_word_len = 8.37891768098732
        std_dev_word_len = 2.585977805143508
        word_len = random.normalvariate(avg_word_len, std_dev_word_len)

        # random word generation from: http://stackoverflow.com/a/367596
        word = "".join( [random.choice(string.letters[:26]) for i in xrange(int(word_len))] )
        return word

    def fake_words(self, how_many):
        "generate a string with the given number of fake words"
        return " ".join([self.fake_word() for i in xrange(how_many)])


    def filter_matches_request(self, filter_definition, request_args):
        request_path = urlparse(request_args.get('url')).path

        # take off the preceding slash
        request_path = re.sub('^/', '', request_path)
        return filter_definition.get('path') == request_path

    def error_filter(self, full_resp, error_probability, possible_error_codes):
        """Take the given response and replace it with a random non-OK response with some frequency
           Args:
              * full_resp - the http response object for the original request
              * error_probability - a number between 0 and 1 representing the probability that the response should
              be replaced with an error
              * possible_error_codes - a list of 3 digit http error codes that should be returned with equal
              probability if we need to simulate an error
           Returns:
              full_resp possibly unchanged, possibly replaced with a generic error response """

        random_number = random.uniform(0, 1.0)
        if random_number < error_probability:
            # this will be expanded to other non-200 responses later
            full_resp.code = random.choice(possible_error_codes)
            full_resp.body = json.dumps({'error': 'something bad happened'})

        return full_resp


    def filter(self, request_args, full_resp):
        """Take the given response and transform it by any filter that matches the `request_args` given
           Args:
              * full_resp - the http response object for the original request
              * request_args - the arguments sent to the request method that originally made the
                 request
           Returns:
              resp as tranformed by any relevant filter from the filter_registry"""
        for filter_definition in ResponseFilter.filter_registry.get(self.__class__.__name__, []):
            if self.filter_matches_request(filter_definition, request_args):
                filter_func = filter_definition.get('func', lambda resp, **request_args: resp)

                if filter_definition.get('parse_json', False):
                    # convert the response from json text to a hash, as the filter function
                    # expects a hash
                    dict_resp = json.loads(full_resp.body)

                    dict_resp = filter_func(self, dict_resp, **request_args)

                    # convert the response from a hash to json text, since the actual request method
                    # expects a textual response
                    full_resp.body = json.dumps(dict_resp)
                else:
                    full_resp = filter_func(self, full_resp, **request_args)

        return full_resp


class ResponseFilterType(type):
    """ This is a metaclass that can register response filters.

    This can be used to add or modify data to be fake for a load test scenario.  It is expected
    that the subclass will either implement a `request(self, **kwargs)` method, or mix in another
    class that does"""

    def __init__(cls, name, bases, attrs):
        for key, val in attrs.iteritems():
            my_filter = getattr(val, 'response_filter', None)
            if my_filter is not None:
                if not ResponseFilter.filter_registry.get(name):
                    ResponseFilter.filter_registry[name] = []
                ResponseFilter.filter_registry[name].append(my_filter)
