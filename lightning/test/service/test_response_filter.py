from __future__ import absolute_import

from lightning.recorder import recorder, RecordedResponse
from lightning.service.response_filter import ResponseFilter, ResponseFilterType, response_filter
from lightning.service.base import Service
from .base import TestService

from twisted.internet import defer


class MockResponseFilter(ResponseFilter):
    __metaclass__ = ResponseFilterType    

    @response_filter(path='year')
    def into_the_future(self, response, **kwargs):
        response['year'] = 3013
        return response


class MockService(Service):

    def __init__(self, *args, **kwargs):
        self.response_filter = MockResponseFilter() 

    def actually_request(self, *args, **kwargs):
        return defer.succeed(RecordedResponse(body='{"year": 2013}')) 


class TestResponseFilter(TestService):
    
    @defer.inlineCallbacks
    def test_response_filter(self):
        ms = MockService()
        recorder.use_filters = True
        recorder.wrap(ms.actually_request)
        recorder.record()
        args = []
        kwargs = {'url': 'http://example.com/year'}
        resp = yield ms.request(**kwargs)
        self.assertEqual(resp['year'], 2013)
        recorder.stop()
        recorder.save()

        resp = yield ms.request(url='http://example.com/year')
        self.assertEqual(resp['year'], 3013)
        # we must turn off filters here, or we'll get strange database errors on setup for other
        # tests
        recorder.use_filters = False
        

