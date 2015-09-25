"Generic docstring A"
from __future__ import absolute_import

from .base import TestService, TestDaemon

from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.facebook import FacebookWeb, FacebookDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

import base64
from bs4 import BeautifulSoup
import json
import logging
import re
import requests
import time
import mock


from pprint import pprint

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'email': 'example@inflection.com',
    'password': 'example1234',
    'username': 'example.lightning',
    'name': 'Example Lightning',
    'first_name': 'Example',
    'last_name': 'Lightning',
    'user_id': '100004005057849',
    'link': 'https://www.facebook.com/example.lightning',
    'gender': 'male',
}

# This is a 'test user'
FACEBOOK_TEST_USER = {
    'email': 'test2@example.com',
    'id': '54321',
    'password': 'testpassword',
}


class FacebookWebMock(FacebookWeb):
    # Override the default behavior for generating a state token, so that it uses what we've recorded
    def generate_random_string(self):
       return 'foobity-foo'


    # Override the current time so that it is consistent between test runs
    def current_timestamp(self):
        return 1357020000

class TestFacebook(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'facebook'
        return super(TestFacebook, self).set_authorization(**kwargs)


class TestFacebookWeb(TestFacebook):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFacebookWeb, self).setUp(*args, **kwargs)
        self.service = FacebookWebMock(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()
        # recorder.record()


    def tearDown(self):
        recorder.save()
        super(TestFacebookWeb, self).tearDown()

    def submit_login_form(self, uri, args):
        login_form = requests.get(
            uri,
            headers=self.headers(),
        )

        soup = BeautifulSoup(login_form.content)
        arguments = self.extract_form_fields(soup.form)

        # The charset_test value has issues being encoded in the post()
        #del arguments['charset_test']

        # We cannot actually use a facebook test user, which is stupid. So,
        # we have to use a fake "real user", which is a violation of
        # Facebook's Terms of Service on at least 3 points. But, what else
        # are we to do?
        arguments['email'] = args['username']
        arguments['pass'] = args['password']

        response = requests.post(
            "https://www.facebook.com%s" % soup.form['action'],
            headers=self.headers(),
            data=arguments,
            cookies=login_form.cookies,
            allow_redirects=False,
        )

        return response



    def handle_grant_permissions(self, response):
        soup = BeautifulSoup(response.content)
        # There's more than one form on this page, so pick the right one.
        form = soup.find_all('form', action=re.compile('permissions'))[0]
        args = self.extract_form_fields(form)
        # This should work, but doesn't. Examine why later.
        #if grant:
        if hasattr(args, 'cancel_clicked'):
            del args['cancel_clicked']
        # This is for the grant extended permissions page, but we don't have it
        # working just yet.
        elif hasattr(args, 'skip_clicked'):
            del args['skip_clicked']
        #else:
        #    del args['grant_clicked']

        return requests.post(
            'https://www.facebook.com' + form['action'],
            headers=self.headers(),
            data=args,
            cookies=response.cookies,
            allow_redirects=False,
        )

    @defer.inlineCallbacks
    def test_authorize(self):
        redir_uri = 'https://lg-local.example.com/authn/facebook'

        expected_redirect = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )

        response = self.submit_login_form(
            uri=expected_redirect,
            args=dict(
                username=AUTHN_TEST_USER['email'],
                password=AUTHN_TEST_USER['password'],
            ),
        )

        response = self.follow_redirect_until_not(response, r'facebook.com')

        # If we get this, it is the "grant permissions to app" page
        if not self.is_redirect(response.status_code):
            self.handle_grant_permissions(response)

        response = self.follow_redirect_until_not(response, r'facebook.com')

        # If we get this, it is the "grant extended permissions to app" page
        if not self.is_redirect(response.status_code):
            self.handle_grant_permissions(response)

        response = self.follow_redirect_until_not(response, r'facebook.com')

        if not self.is_redirect(response.status_code):
            self.display_error(response, "Failed to grant permissions")
            return

        args = get_arguments_from_redirect(response)
        args['redirect_uri'] = redir_uri

        user_auth = yield self.service.finish_authorization(
            client_name='testing',
            args=args,
        )
        # Do we have a better test for the oauth_token?
        self.assertTrue(user_auth.token)
        self.assertEqual(AUTHN_TEST_USER['user_id'], user_auth.user_id)

        # What happens when we authenticate the same user again against FB?
        # Supposedly, we get a new oauth token. Is this correct?

        # Verify this authorization is any good.
        yield self.set_authorization(
            user_id=user_auth.user_id, token=user_auth.token,
        )

        # Verify that we get the fist activity time correct
        result = yield self.call_method('account_created_timestamp')
        got_timestamp = result['timestamp']
        expected_timestamp = 1341941735
        month_in_seconds = 31 * 24 * 60 * 60

        # make sure the timestamp we got is within 31 days of the one we expect
        self.assertLess(abs(got_timestamp - expected_timestamp), month_in_seconds)


        # some of the other methods seem to blow up when we call self.run_daemon() for facebook, so
        # just call the one we need
        yield self.run_daemon_method('profile')
        profile = yield self.call_method('profile')

        expected_profile = dict(
            bio=None,
            email=AUTHN_TEST_USER['email'],
            first_name=AUTHN_TEST_USER['first_name'],
            gender=AUTHN_TEST_USER['gender'],
            headline=None,
            last_name=AUTHN_TEST_USER['last_name'],
            middle_name=None,
            name=AUTHN_TEST_USER['name'],
            profile_link=AUTHN_TEST_USER['link'],
            profile_picture_link='https://graph.facebook.com/100004005057849/picture',
            username=AUTHN_TEST_USER['username'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        birth = yield self.call_method('birth')
        expected_birth = dict(
            age=37,
            dob_day=16,
            dob_month=1,
            dob_year=1977,
        )
        self._test_method_result_keys('birth', birth, expected_birth)
        website = yield self.call_method('website')
        expected_website = dict(
            website='http://google.com'
        )
        self.assertEqual(website, expected_website)
        contact = yield self.call_method('contact')
        expected_contact = dict(
            city=None,
            country_code=None,
            phone_numbers=None,
            region=None,
            state=None,
        )
        self.assertEqual(contact, expected_contact)
        work = yield self.call_method('work')
        expected_work = {'data': [dict(
            city='Redwood City',
            end_date_month=None,
            end_date_year=None,
            is_current=None,
            organization_name='Inflection',
            start_date_month=9,
            start_date_year=2011,
            state='CA',
            title='Software Engineer',
            work_id=None,
        )]}
        self.assertEqual(work, expected_work)
        education = yield self.call_method('education')
        expected_education = {'data': [dict(
            degree_earned='MSc',
            end_date_month=None,
            end_date_year=2013,
            field_of_study='Computer Engineering, Hustlin, Bachelor of Science in Animal Husbandry',
            school_name='School of Hard Knocks',
            start_date_month=None,
            start_date_year=None,
            education_id=None,
        )]}
        self.assertEqual(education, expected_education)

    #@defer.inlineCallbacks
    def notest_authorize_with_error(self):
        self.skip_me("Disabled until extended permissions are supported")

        redir_uri = 'https://lg-local.example.com/authn/facebook'

        expected_redirect = compose_url(
            'https://graph.facebook.com/oauth/authorize',
            query={
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'scope': self.service.permissions['testing']['scope'],
            },
        )
        rv = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertURIEqual(rv, expected_redirect)

        response = self.submit_login_form(
            uri=expected_redirect,
            args=dict(
                username=AUTHN_TEST_USER['email'],
                password=AUTHN_TEST_USER['password'],
            ),
        )

        response = self.follow_redirect_until_not(response, r'facebook.com')

        # If we get this, it is the "grant permissions to app" page
        if not self.is_redirect(response.status_code):
            logging.info("Denying the grant permissions")
            self.handle_grant_permissions(response, grant=False)

        response = self.follow_redirect_until_not(response, r'facebook.com')

        if not self.is_redirect(response.status_code):
            self.display_error(response, "Failed to grant permissions")
            return

        code = re.search(r'code=(.*)', response.headers['location']).group(1)
        user_auth = yield self.service.finish_authorization(
            client_name='testing',
            args={
                'redirect_uri': redir_uri,
                'code': code,
            },
        )
        # Do we have a better test for the oauth_token?
        self.assertTrue(user_auth.token)
        self.assertEqual(AUTHN_TEST_USER['user_id'], user_auth.user_id)

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the approximate (to within a month) time at which the user first posted to this service',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_friend_requests': "Returns this user's number of friend requests",
                'num_friend_requests_interval': "Returns this user's number of friend requests over time",
                'num_friends': "Returns this user's number of friends.",
                'num_friends_interval': "Returns this user's number of friends over time.",
                'num_photos_uploaded': "Returns number of photos uploaded by this user.",
                'num_photos_uploaded_interval': "Returns number of photos uploaded by this user over time.",
                'num_likes_photos': "Returns number of likes for photos uploaded by this user.",
                'num_likes_photos_interval': "Returns number of likes for photos uploaded by this user over time.",
                'num_comments_photos': "Returns number of comments on photos uploaded by this user.",
                'num_comments_photos_interval': "Returns number of comments on photos uploaded by this user over time.",
                'profile': "Returns this user's profile.",
                'person_commented': 'Retrieve data for all comments, storing the results granularly.',
                'education': "Returns this user's education information",
                'work': "Returns this user's work information",
                'birth': "Returns this user's birth information",
                'website': "Returns this user's website information",
                'contact': "Returns this user's contact information",
                'random_friend_id': "Returns a random friend_id from this user's friends.",
            },
            'POST': {},
        })

    @defer.inlineCallbacks
    def test_num_friends_and_interval(self):
        yield self.set_authorization()

        yield self.write_value(method='num_friends', data='10', timestamp=100)
        rv = yield self.call_method('num_friends')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_friends_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data':[
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_friends', data='12', timestamp=105)
        rv = yield self.call_method('num_friends')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_friends_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data':[
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_friend_requests_and_interval(self):
        yield self.set_authorization()

        # first call to friend requests
        yield self.write_value(method='num_friend_requests', data='4', timestamp=100)
        rv = yield self.call_method('num_friend_requests')
        self.assertEqual(rv, {'num': 4})

        # check that the interval shows the correct number
        rv = yield self.call_method('num_friend_requests_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 4 }
        ]})

        # test interval after we add another value
        yield self.write_value(method='num_friend_requests', data='12', timestamp=105)
        rv = yield self.call_method('num_friend_requests')
        self.assertEqual(rv, {'num': 12})

        rv = yield self.call_method('num_friend_requests_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data':[
            {'timestamp': '100', 'num': 4},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_service_revoke(self):
        self.skip_me("Disabled until implemented in SQL server")
        yield self.set_authorization()
        data = {'user_id': 'asdf', 'algorithm': 'HMAC-SHA256'}
        encoded_json = base64.urlsafe_b64encode(json.dumps(data))
        encoded_json = encoded_json.replace('=', '')
        signature = self.service._generate_signature(encoded_json)
        signed_request = "%s.%s" % (signature, encoded_json)
        response = yield self.post_and_verify(
            path='/auth/facebook',
            args=dict(
                signed_request=signed_request,
            ),
            response_code=200,
        )
        self.assertEqual(response.body, {'success': 'Revocation successful'})

    def test_num_photos_uploaded_and_interval(self):
        yield self.set_authorization()

        yield self.write_value(method='num_photos_uploaded', data='10', timestamp=100)
        rv = yield self.call_method('num_photos_uploaded')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method(
            'num_photos_uploaded_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_photos_uploaded', data='12', timestamp=105)
        rv = yield self.call_method('num_photos_uploaded')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method(
            'num_photos_uploaded_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_likes_photos_and_interval(self):
        yield self.set_authorization()

        yield self.write_value(method='num_likes_photos', data='10', timestamp=100)
        rv = yield self.call_method('num_likes_photos')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method(
            'num_likes_photos_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_likes_photos', data='12', timestamp=105)
        rv = yield self.call_method('num_likes_photos')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method(
            'num_likes_photos_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})


class TestFacebookDaemon(TestDaemon, TestFacebook):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFacebookDaemon, self).setUp(*args, **kwargs)
        self.service = FacebookDaemon(
            datastore=self.app.db,
        )

# This one is for tests that don't want a test-user created. That takes an
# additional 8-10 seconds per test method.
# class TestFacebookDaemonNoUser(TestFacebookDaemon):
#     def test_methods(self):
#         self.skip_me("Need to discuss this with Ray")
#         self.assertEqual( self.service.methods(), {
#             #'num_comments': "Returns number of comments by this user.",
#             'num_friends': "Returns this user's number of friends.",
#             'num_photos': "Returns number of photos uploaded by this user.",
#         })


# These are disabled because they timeout most of the time. There needs to be a
# better way to run these tests.
class TestFacebookDaemonWithUser():#TestFacebookDaemon):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFacebookDaemonWithUser, self).setUp(*args, **kwargs)

        self.test_user = self.service.generate_test_user(
            full_name='Some User',
        )
        yield self.set_authorization(
            user_id=self.test_user['id'],
            token=self.test_user['access_token'],
        )

        self.start_pyres()

    @defer.inlineCallbacks
    def tearDown(self, *args, **kwargs):
        self.stop_pyres()

        if hasattr(self, 'test_user'):
            self.service.delete_test_user(self.test_user)

        yield super(TestFacebookDaemonWithUser, self).tearDown(*args, **kwargs)

    @defer.inlineCallbacks
    def test_run(self):
        # Enqueue something with pyres
        yield self.resq.enqueue(
            FacebookDaemon, {
                'redis': self.service.datastore.config,
                'environment': 'local',
            }, self.uuid,
        )

        # Wait for the scheduler and the worker
        time.sleep(7)

        # See the piece of data in the database
        data = {}
        for method in self.service.methods().keys():
            data[method] = yield self.get_value(
                uuid=self.uuid,
                method=method,
            )

        self.assertEqual(data['num_friends'], '0')
        self.assertEqual(data['num_friend_requests'], '0')
        self.assertEqual(data['num_posts'], '0')
        self.assertEqual(data['num_photos_uploaded'], '0')
        self.assertEqual(data['num_likes_photos'], '0')
        self.assertEqual(data['num_comments_photos'], '0')


class TestFacebookDaemonWithSecondUser():#TestFacebookDaemon):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFacebookDaemonWithSecondUser, self).setUp(*args, **kwargs)

        self.test_users = [
            self.service.generate_test_user(
                full_name='Some User',
            ),
            self.service.generate_test_user(
                full_name='Some Other User',
            ),
        ]

    @defer.inlineCallbacks
    def tearDown(self, *args, **kwargs):
        if hasattr(self, 'test_users'):
            for user in self.test_users:
                self.service.delete_test_user(user)

        yield super(TestFacebookDaemonWithSecondUser, self).tearDown(*args, **kwargs)

    @defer.inlineCallbacks
    def test_with_friends(self):
        self.service.make_friends(self.test_users[0], self.test_users[1])

        yield self.set_authorization(
            user_id=self.test_users[0]['id'],
            token=self.test_users[0]['access_token'],
        )

        yield self.service.run(
            authorization=self.authorization,
            timestamp=int(time.time()),
        )

        data = {}
        for method in self.service.recurring().keys():
            datum = yield self.get_value(
                uuid=self.uuid,
                method=method,
            )
            data[method] = datum
        self.assertEqual(data['num_friends'], '1')
        self.assertEqual(data['num_friend_requests'], '0')
