"""
This is the place the web application class for Lightning is defined.
"""
from __future__ import absolute_import

from twisted.internet import defer
from twisted.python import log
from twisted.web import server


import logging

from lightning.datastore.sql import DatastoreSQL
from lightning.messaging import Email

from lightning.server import Request
from lightning.handlers import ErrorHandler, resource_tree
from lightning.service.web import WEB_MODULES
from cyclone import redis

import sys

from twisted.web.resource import Resource

class Lightning(object):

    "The application class for the Lightning service"
    def __init__(self, config, do_connect_redis=True):
        self.email = Email(
            host=config.get(
                'email_host', 'mail.example.com'),
            username=config.get('email_username', 'lightning@example.com'),
            password=config.get('email_password', 'fakepassword'),
            default_to=config.get(
                'email_default_to', 'lightning-errors@example.com'),
            default_from=config.get(
                'email_default_from', 'lightning@example.com'),
            environment=config.get('environment', 'local'),
        )

        if do_connect_redis:
            self.redis = redis.lazyConnectionPool(
                config['redis_host'],
                config['redis_port'],
            )



    def initialize(self, config):
        """
        This is how we initialize a Lightning app object. This has to be done
        afterwards so that the datastore can be connected and ready.
        """
        # This is where we pass in which environment stack we're running in.
        # This is needed for the service objects to know which configuration to
        # use. This configuration needs to be hoisted into an environment-level
        # service, such as hiera (provided by Puppet). That will come later.

        service_args = dict(
            config=config,
            datastore=self.db,
        )
        self.config = config
        self.services = {
            module.name: module(**service_args)
            for module in WEB_MODULES
        }
        if config.get('record') or config.get('play'):
            from .recorder import recorder
            recorder._input_file = 'etc/load_test_recorded_response.json'
            recorder._output_file = 'etc/load_test_recorded_response.json'
            # XXX(ray): record mode defaults to modifying the test file, use
            # the above paths for debugging.

            # recorder._input_file = 'lightning/test/etc/recorded_response.json'
            # recorder._output_file = 'lightning/test/etc/recorded_response.json'


            for k in self.services:
                recorder.wrap(self.services[k].actually_request)

            recorder.load()

            if config.get('use_filters'):
                recorder.use_filters = True

            if config.get('simulate_delays_and_errors'):
                recorder.simulate_delays_and_errors = True


            if config.get('record'):
                recorder.record()

        logging.info("Lightning started")

        # TODO: figure out twisted.web equivalent of ErrorHandlers
        #web.ErrorHandler = ErrorHandler

        root = resource_tree(self)
        self.site = server.Site(root)
        self.site.requestFactory = Request

    def shutdown(self):
        return self.redis.disconnect()


    @classmethod
    def build(cls, config, do_connect_redis=True):
        "This is how we create a Lightning app object."
        obj = cls(config, do_connect_redis=do_connect_redis)

        def on_connect(db):
            'Callback'
            obj.db = db
            obj.initialize(config)
            return obj

        return defer.maybeDeferred(
            DatastoreSQL.connect,
            config.get('sql_connection', 'dsn=SQLServer;uid=fakeuser;pwd=fakepassword;database=fakedb;driver={SQL Server Native Client 10.0}'),
        ).addCallback(on_connect)
