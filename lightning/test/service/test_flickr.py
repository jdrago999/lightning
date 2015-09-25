from __future__ import absolute_import

from .base import TestService, TestDaemon
from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.flickr import FlickrWeb, FlickrDaemon

from bs4 import BeautifulSoup
import requests
import json
import time
from urlparse import parse_qsl

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'id': '1234',
    'email': '',  # Signed up with example@example.com
    'profile_link': 'http://www.flickr.com/people/example/',
    'username': 'example',
    'password': 'testpassword',
    'name': 'Example User',
    'bio': "Example User, now with photos!",
    'profile_picture_url': 'http://farm9.staticflickr.com/1234/buddyicons/123448@N06.jpg',
    'num_photos': 1,
}


class TestFlickr(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id', 'secret']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'flickr'

        return super(TestFlickr, self).set_authorization(**kwargs)


class TestFlickrWeb(TestFlickr):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFlickrWeb, self).setUp(*args, **kwargs)
        self.service = FlickrWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        # recorder.record()

    def tearDown(self):
        recorder.save()
        super(TestFlickrWeb, self).tearDown()

    def submit_login_form(self, uri, args):
        pass

    @defer.inlineCallbacks
    def test_authorize(self):
        self.skip_me("disabled to be replaced by new auth test method")

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
             'GET': {
                 'account_created_timestamp': 'Returns the timestamp this user account was created on',
                 'most_recent_activity': "The most recent activity on this service's feed",
                 'recent_content_authored': "The recent content authored by this user",
                 'num_contacts': 'Number of contacts this user has added.',
                 'num_contacts_interval': 'Number of contacts this user has added over time.',
                 'num_favorites': 'Number of photos this user has favorited.',
                 'num_favorites_interval': 'Number of photos this user has favorited over time.',
                 'num_galleries': 'Number of galleries this user has created.',
                 'num_galleries_interval': 'Number of galleries this user has created over time.',
                 'num_photos': 'Number of photos.',
                 'num_photos_interval': 'Number of photos over time.',
                 'num_photosets': 'Number of photosets this user has created.',
                 'num_photosets_interval': 'Number of photosets this user has created over time.',                 'profile': "Returns this user's profile."
             },
             'POST': {}
        })

    @defer.inlineCallbacks
    def test_num_photos_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_photos', data='10', timestamp=100)
        rv = yield self.call_method('num_photos')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_photos_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_photos', data='12', timestamp=105)
        rv = yield self.call_method('num_photos')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_photos_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})
