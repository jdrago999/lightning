from __future__ import absolute_import

import os
import sys

from twisted.internet import defer, task
from lightning.recorder import recorder
from cyclone import redis

import datetime as dt
import json
import time
import traceback

class ResQ(object):
    def __init__(self, redis=None, server='localhost:6379'):

        # If our client already has a redis object, we can use that, otherwise they must call `connect`
        if redis:
            self.redis = redis

        # Set the host, port, dsn, etc for clients that don't already have a redis connection.  The
        # connect method will  use these.
        if not isinstance(server, basestring):
            raise Exception("I don't know what to do with %s" % str(server))

        self.dsn = server
        host, port = server.split(':')
        self.host = host
        self.port = int(port)

    @classmethod
    def connect(cls, server='localhost:6379'):
        obj = cls(redis=None, server=server)

        d = redis.Connection(obj.host, obj.port)

        def on_connect(connection):
            obj.redis = connection
            return obj
        d.addCallback(on_connect)

        return d

    def disconnect(self):
        return self.redis.disconnect()

    def key_from_queue(self, queue):
        'Convert a queue name into a key'
        return "resque:queue:%s" % queue
    def key_from_worker(self, worker):
        'Convert a worker name into a key'
        return "resque:worker:%s" % worker
    def fail_key(self):
        'Return the key of the failure holding area'
        return "resque:failed"

    def push(self, queue, item):
        'Add an item in a queue'
        return self.redis.rpush(self.key_from_queue(queue), ResQ.encode(item))

    def delayed_push(self, datetime, item):
        "Add a job to be worked on in the future"

        key = int(time.mktime(datetime.timetuple()))

        # XXX This really should be a transaction, not a pair of Deferreds.
        return defer.gatherResults([
            self.redis.rpush('resque:delayed:%s' % key, ResQ.encode(item)),
            self.redis.zadd('resque:delayed_queue_schedule', key, key),
        ])

    def pop(self, queue):
        "Return the next job to be worked on."
        # Note that blpop from tornado-redis would return a hash instead of a
        # tuple like pyredis or cyclone.redis does. Adjust accordingly if using
        # tornadoredis.
        d = self.redis.blpop(
            keys=[self.key_from_queue(queue)],
            timeout=1,
        )
        def decode_value(ret):
            if ret:
                return ResQ.decode(ret[1])
            return None
        d.addCallback(decode_value)
        return d

    def enqueue(self, klass, *args, **kwargs):
        """Enqueue a job into a specific queue. Make sure the class you are
        passing has **queue** attribute and a **perform** method on it.

        """
        return self.enqueue_from_string(
            klass.__name__, klass.queue, *args, **kwargs
        )

    def enqueue_from_string(self, klass_as_string, queue, *args, **kwargs):
        payload = {
            'class':klass_as_string,
            'args':args,
            'enqueue_timestamp': time.time(),
        }
        return self.push(queue, payload)

    def enqueue_at(self, datetime, klass, *args, **kwargs):
        return self.enqueue_at_from_string(
            datetime, klass.__name__, klass.queue, *args, **kwargs
        )

    def enqueue_at_from_string(self, datetime, klass_as_string, queue, *args, **kwargs):
        payload = {'class': klass_as_string, 'queue': queue, 'args': args}
        return self.delayed_push(datetime, payload)

    def add_job(self, worker, job):
        return self.redis.sadd(self.key_from_worker(worker), [job])

    def remove_job(self, worker, job):
        return self.redis.srem(self.key_from_worker(worker), [job])

    @classmethod
    def encode(cls, item):
        return json.dumps(item)

    @classmethod
    def decode(cls, item):
        if isinstance(item, basestring):
            ret = json.loads(item)
            return ret
        return None

    def add_failure(self, data):
        return self.redis.rpush(self.fail_key(), data)

class JobFailure(object):
    def __init__(self, exp, queue, payload, worker=None):
        excc, _, tb = sys.exc_info()
        self.exception = excc
        self.traceback = traceback.format_exc()
        self.worker = worker
        self.queue = queue
        self.payload = payload

    def parse_traceback(self, trace):
        """Return the given traceback string formatted for a notification."""
        if not trace:
            return []

        return trace.split('\n')

    def parse_message(self, exc):
        """Return a message for a notification from the given exception."""
        return '%s: %s' % (exc.__class__.__name__, str(exc))

    def save(self, resq):
        data = {
            'failed_at' : dt.datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'payload'   : self.payload,
            'exception' : self.exception.__class__.__name__,
            'error'     : self.parse_message(self.exception),
            'backtrace' : self.parse_traceback(self.traceback),
            'queue'     : self.queue
        }
        if self.worker:
            data['worker'] = self.worker
        data = ResQ.encode(data)
        return resq.add_failure(data)

class Job(object):
    def __init__(self, queue, payload, resq, classlist, worker):
        self.resq = resq
        self.payload = payload
        self.queue = queue
        self.worker = worker
        self.classlist = classlist

    def perform(self):
        payload_class = self.classlist.get(self.payload['class'])
        args = self.payload.get('args')
        return payload_class.perform(*args)

    @classmethod
    def reserve(cls, queue, resq, classlist, worker_name):
        d = resq.pop(queue)
        def build_job(payload):
            if payload:
                return cls(queue, payload, resq, classlist, worker_name)
            return None
        d.addCallback(build_job)
        return d

    def fail(self, exception):
        """
        Saves the failed Job into a "failed" Redis queue preserving all its
        original enqueud info.
        """
        failure = JobFailure(exception, self.queue, self.payload, self.worker)
        d = failure.save(self.resq)
        def return_failure(_):
            return failure
        d.addCallback(return_failure)
        return d

class Worker(object):
    job_class = Job
    max_jobs = 10

    def __init__(self, queue):
        self.queue = queue
        self.pid = os.getpid()
        self.hostname = os.uname()[1]

        self.semaphore = defer.DeferredSemaphore(self.max_jobs)
        self.looper = task.LoopingCall(self.work)

    @classmethod
    def create(cls, queue, server, classlist, datastore, record, play, use_filters, simulate_delays_and_errors):
        obj = cls(queue)

        d = ResQ.connect(server)
        def set_resq(resq):
            obj.resq = resq
            obj.classlist = classlist

            # Set up recorder
            if record or play:
                recorder._input_file = 'etc/load_test_recorded_response.json'
                recorder._output_file = 'etc/load_test_recorded_response.json'

                # XXX(ray): record mode defaults to modifying the test file, use
                # the above paths for debugging.
                # recorder._input_file = 'lightning/test/etc/recorded_response.json'
                # recorder._output_file = 'lightning/test/etc/recorded_response.json'

                recorder.load()
                if use_filters:
                    recorder.use_filters = True

                if simulate_delays_and_errors:
                    recorder.simulate_delays_and_errors = True

                if record:
                    recorder.record()

            # Set the resq attribute. These are singletons and they need access
            # to it for re-queueing as appropriate.
            for klass in classlist.values():
                klass.resq = resq
                klass.datastore = datastore
                klass.record = record
                klass.play = play


            return obj

        d.addCallback(set_resq)

        return d

    def __str__(self):
        if getattr(self,'id', None):
            return self.id
        return '%s:%s:%s' % (self.hostname, self.pid, self.queue)

    def work(self):
        return (
            self.semaphore.run(self.reserve)
                .addCallback(self._perform_work)
                #.addErrback(log.err, 'error scheduling work')
        )

    def _perform_work(self, job):
        if not job:
            return

        return (
            self.working_on(job)
                .addCallback(lambda _: job.perform())
                .addErrback(lambda _: self.handle_job_exception(job))
                .addBoth(lambda _: self.done_working(job))
        )

    def handle_job_exception(self, job):
        _, _, exceptionTraceback = sys.exc_info()
        d = job.fail(exceptionTraceback)
        d.addCallback( lambda _: self.failed() )
        return d

    def done_working(self, job):
        self.processed()
        return self.resq.remove_job(str(self), job.payload)

    def processed(self):
        # Note the processed in statsd
        pass

    def failed(self):
        # Note the failure in statsd
        pass

    def reserve(self):
        return self.job_class.reserve(
            self.queue,
            self.resq,
            self.classlist,
            str(self),
        )

    def working_on(self, job):
        return self.resq.add_job(str(self), job.payload)

    @classmethod
    def run(cls, *args, **kwargs):
        return (
            cls.create(*args, **kwargs)
                .addCallback( lambda obj: obj.looper.start(0.01) )
        )
