from lightning.model import DatastoreModel

from functools import wraps
import random
import time
from twisted.internet import defer, reactor

class Limit(DatastoreModel):
    TABLENAME = "[Limit]"

    @classmethod
    def request_rate(cls, max, every='second'):
        """Limit the request rate of a function per uuid.

        Args:
           max: int, Max number of executions that can happen per `every`.
           every: string, time period that max must occur within. ["second", "minute", "hour"]

        Returns:
           A new function that can will only execute deferreds within the rate
        """
        unit_to_seconds = {
            'second': 1,
            'minute': 60,
            'hour': 60 * 60,
        }

        max_per_second =  float(max) / float(unit_to_seconds.get(every, 1))
        min_interval = 1.0 / max_per_second
        def limit_decorator(fn):

            @wraps(fn)
            def wrapped_request(*args, **kwargs):
                def update_last_called_on(limit):
                    """Update our last_called_on to the current time"""
                    if limit:
                        limit.last_called_on = time.time()
                        limit.save()

                def reset_timer(tramp):
                    """reset the last time we were called for this user to the current time.
                    if we don't have a user, do nothing and proceed as notmal"""

                    if uuid:
                        return Limit.find(where=['uuid = ?', uuid], limit=1).addBoth(update_last_called_on)
                    return tramp

                def do_request(_):
                    d = fn(*args, **kwargs)
                    return d

                def execute(_):
                    """Call our original function and reset the timer"""

                    if uuid:
                        # Use optimistic locking: set the request time in the database first, *then* make the request
                        # That way if the request takes a long time, we'll have already let others know not to
                        # make requests just yet
                        return reset_timer(None).addCallback(do_request)
                    else:
                        # We don't need to worry about reseting the timer if the request isn't associated with a user
                        return do_request(None)

                def try_to_execute_limit(limit):
                    """Check the last_called_on of our limit and either wait
                    or execute."""
                    if limit:
                        elapsed = time.time() - limit.last_called_on
                        if elapsed < min_interval:
                            # The random amount added to wait_time is to ensure
                            # we don't hit a race condition. This does err on
                            # the side of waiting longer, but the services this
                            # is used for are strict so we're being cautious.
                            wait_time = min_interval + (random.random() * min_interval)
                            reactor.callLater(wait_time, try_to_execute)
                        else:
                            # Execute
                            reset_timer(None)
                            ret.callback(None)


                def try_to_execute():
                    """Check our limit and attempt to execute the request"""
                    if uuid:
                        Limit.find(where=['uuid = ?', uuid], limit=1).addBoth(try_to_execute_limit)
                    else:
                        ret.callback(None)


                def create_new_limit(limit):
                    """Create new limit if not found"""
                    if not limit:
                        Limit(uuid=uuid, last_called_on=time.time()).save()

                uuid = None
                authorization = kwargs.get('authorization')
                if authorization:
                    uuid = authorization.uuid
                    Limit.find(where=['uuid = ?', uuid], limit=1).addBoth(create_new_limit)

                ret = defer.Deferred()
                ret.addCallback(execute)
                try_to_execute()

                return ret

            return wrapped_request

        return limit_decorator

    @classmethod
    def max_simultaneous_calls(cls, simul_calls):
        """
        This is a decorator that will limit the number of simultaneous deferreds that
        can execute at a time. It assumes that the decorated function returns a
        deferred. It will add a callback to release the slot taken.

        This isn't an exact science. It's possible for the actual number of calls to
        be within 1 or 2 of simul_calls. So, simul_calls=10 may allow up to 12 in
        flight at a time.
        """
        def limit_decorator(fn):
            available_slots = [simul_calls]

            @wraps(fn)
            def wrapper(*args, **kwargs):
                ret = defer.Deferred()

                def free_the_slot(tramp):
                    available_slots[0] += 1
                    return tramp

                def execute(_):
                    d = fn(*args, **kwargs)
                    d.addBoth(free_the_slot)
                    return d

                ret.addCallback(execute)

                def try_to_execute():
                    if available_slots[0] <= 0:
                        reactor.callLater(1, try_to_execute)
                    else:
                        available_slots[0] -= 1
                        ret.callback(None)

                try_to_execute()

                return ret

            return wrapper

        return limit_decorator
