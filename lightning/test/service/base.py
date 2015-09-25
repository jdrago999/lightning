from __future__ import absolute_import

from ..base import TestLightning

from twisted.internet import defer
from bs4 import BeautifulSoup
from lightning.recorder import recorder
from lightning.service.base import Profile
import logging
import os
import time
import re
import requests
from subprocess import Popen, PIPE, STDOUT
from twistedpyres import ResQ

USER_AGENT = dict(
    firefox='Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:13.0) Gecko/20100101 Firefox/13.0.1',
)

recorder.wrap(requests.request)

class TestService(TestLightning):
    def _test_method_result_keys(self, method_name, result, expected_result=None):
        """
        This method verifies that the result value passed in matches the values that
        we expect for the given method.

        For example, we could test the method return value of profile.  This method
        will verify that all the profile keys (first_name, last_name, etc) are contained
        in the return value.

        method_name: the method to compare the result again
        result: the result to test against the expected result
        """

        # contains all the proper keys for each of the methods we return
        method_expected_keys = dict(
            birth=[
                'age',
                'dob_day',
                'dob_month',
                'dob_year',
            ],
            contact=[
                'city',
                'country_code',
                'phone_numbers',
                'region',
                'state',
            ],
            education=[
                'degree_earned',
                'education_id',
                'end_date_month',
                'end_date_year',
                'field_of_study',
                'school_name',
                'start_date_month',
                'start_date_year',
            ],
            profile=[
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
            ],
            work=[
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
        )

        assert method_name in method_expected_keys
        expected_keys = set(method_expected_keys.get(method_name))

        if expected_result:
            expected_result_keys = set(expected_result.keys())
        else:
            expected_result_keys = set([])

        # our expected keys should match exactly to what we got
        self.assertEqual(
            expected_keys ^ set(result.keys()),
            set([])
        )

        # verify that expected_result only contains valid keys
        self.assertEqual(
            expected_result_keys - expected_keys,
            set([])
        )

        for i in iter(expected_result_keys):
            self.assertEqual(str(result[i]),str(expected_result[i]),'verify '+i)

        # all other values should be empty
        for i in iter(expected_keys - expected_result_keys):
            self.assertEqual(result[i],None, 'verify %s is None'%i)

    @defer.inlineCallbacks
    def run_daemon_method(self, method):
        yield self.service.daemon_object().run(
            authorization=self.authorization,
            timestamp=int(time.time()),
            daemon_method=method,
        )


    @defer.inlineCallbacks
    def run_daemon(self):
        for method in self.service.daemon_object()._recurring:
            yield self.run_daemon_method(method)

    def headers(self, **kwargs):
        """
        Set up the headers.

        Default the user-agent to a Firefox UA.
        """
        if type(kwargs) == None:
            kwargs = dict()
        kwargs['user_agent'] = USER_AGENT['firefox']
        return kwargs

    def is_redirect(self, code):
        """
        Is the code a redirect HTTP code or not?
        """
        return code == 302

    def follow_redirect_until_not(self, response, condition):
        """
        Given response (a HTTP.Response object), follow the redirect chain until
        either the response is not a redirect (per self.is_redirect) OR the
        location does not match condition (a re object).

        This is used to follow the redirect chain until we get to a call back to
        us from the external third party. However, there might be a second page
        for authorization after the authentication page (Facebook might have
        one).
        """
        while self.is_redirect(response.status_code) and re.search(condition, response.headers['location']):
            response = requests.get(
                response.headers['location'],
                headers=self.headers(),
                cookies=response.cookies,
                # We need to trap the redirect back to localhost:5000
                allow_redirects=False,
            )
        return response

    def display_response(self, response):
        if not os.environ.get('VERBOSE'):
            return
        print
        print("----------------------------------------")  # 40x'-'
        print(response.status_code)
        for k in sorted(response.headers.keys()):
            print('%s: %s' % (k, response.headers[k]))
        soup = BeautifulSoup(response.content)
        print(soup.prettify())

    def display_error(self, response, msg):
        self.display_response(response)
        self.assertTrue(False, msg)

    def extract_form_fields(self, soup):
        "Turn a BeautifulSoup form in to a dict of fields and default values"
        fields = {}
        for inpt in soup.find_all('input'):
            # ignore submit/image with no name attribute
            if inpt['type'] in ('submit', 'image') and not inpt.has_key('name'):
                continue

            # single element nome/value fields
            if inpt['type'] in ('text', 'hidden', 'password', 'submit', 'image'):
                value = ''
                if inpt.has_key('value'):
                    value = inpt['value']
                if inpt.has_key('name'):
                    fields[inpt['name']] = value
                continue

            # checkboxes and radios
            if inpt['type'] in ('checkbox', 'radio'):
                value = ''
                if inpt.has_key('checked'):
                    if inpt.has_key('value'):
                        value = inpt['value']
                    else:
                        value = 'on'
                if fields.has_key(inpt['name']) and value:
                    fields[inpt['name']] = value

                if not fields.has_key(inpt['name']):
                    fields[inpt['name']] = value

                continue

            #assert False, 'inpt type %s not supported' % inpt['type']

        # textareas
        for textarea in soup.find_all('textarea'):
            fields[textarea['name']] = textarea.string or ''

        # select fields
        for select in soup.find_all('select'):
            value = ''
            options = select.find_all('option')
            is_multiple = select.has_key('multiple')
            selected_options = [
                option for option in options
                if option.has_key('selected')
            ]

            # If no select options, go with the first one
            if not selected_options and options:
                selected_options = [options[0]]

            if not is_multiple:
                assert(len(selected_options) < 2)
                if len(selected_options) == 1:
                    value = selected_options[0]['value']
            else:
                value = [option['value'] for option in selected_options]

            fields[select['name']] = value

        return fields

    def call_method(self, method, **kwargs):
        if not kwargs.get('authorization'):
            assert self.authorization, 'Did you call set_authorization() yet?'
        return getattr(self.service, method)(
            authorization=kwargs.get('authorization', self.authorization),
            arguments=kwargs.get('arguments', {}),
        )

class TestDaemon():
    def start_pyres(self):
        # I don't think we actually need the scheduler in the tests. This is
        # likely a mistake.
        #self.scheduler = Popen(
        #    args=['pyres_scheduler', '--port', str(self.redis_port)],
        #    stdout=PIPE, stderr=STDOUT,
        #)

        # Needed because I can't seem to get the env parameter to Popen to work
        os.environ['PYTHONPATH'] = os.path.dirname(__file__) + '/../../..'
        self.worker = Popen(
            args=[
                '%s/bin/worker' % os.environ['PYTHONPATH'],
                '--server=localhost:%d' %(self.redis_port),
                '--queue=Service',
                '--log=INFO',
            ],
#            stdout=PIPE, stderr=STDOUT,
        )

        d = ResQ.connect(
            server=':'.join([
                'localhost',
                str(self.redis_port),
            ]),
        )
        def set_resq(resq):
            self.resq = resq
        d.addCallback(set_resq)

        return d

    def stop_pyres(self):
        # Has to be in this order, or communicate() will hang until terminate()
        self.worker.terminate()
        (worker_stdout, worker_stderr) = self.worker.communicate()
        self.worker.wait()

        #self.scheduler.terminate()
        #(scheduler_stdout, scheduler_stderr) = self.scheduler.communicate()
        #self.scheduler.wait()

        return self.resq.disconnect()
