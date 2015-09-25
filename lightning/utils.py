"""
Generic utilities that don't really fit anywhere else.
"""

from __future__ import absolute_import

import base64
import collections
from datetime import datetime, timedelta
from urllib import urlencode
from urlparse import parse_qs, urlsplit, urlunsplit
from uuid import uuid4  # uuid4() is the creation of a random UUID
import os
import re
import time

VERSION = '15.28.a'

def get_lightning_path():
    """Returns the path to the base lightning folder."""
    return os.path.join(os.path.dirname(__file__), '..')

def get_config_filename(environment):
    """Returns the full path and filename to a Lightning config.
    Args:
        environment: A string representing the Lightning environment.
    """
    assert environment in ['dev', 'local', 'beta', 'preprod', 'prod']
    config_file = 'conf/lightning-%s.conf' % environment
    return os.path.join(get_lightning_path(), config_file)

def create_post_id(post_type, post_id):
    return '%s:%s' % (post_type, post_id)

def flatten(l):
    "recursively flatten the given list, `l`. Taken from: http://stackoverflow.com/a/2158532/30529"
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, basestring):
            for sub in flatten(el):
                yield sub
        else:
            yield el

def timestamp_to_utc(seconds=None):
    "Convert a local timestamp to a utc time string, as per section 5 of rfc3339"

    # We set default seconds here, because if we do so above, seconds will be set to the time that
    # the lightning service started, not the current time
    if not seconds:
        seconds = int(time.time())
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def compose_url(url, **kwargs):
    """
    Given a URL, selectively replace pieces of it with values in **kwargs
    This uses urlparse.urlsplit() for parsing and the kwargs keys must
    conform to it. Those are:
      * scheme
      * netloc
      * path
      * query (assumes a dict, not something returned by parse_qs())
      * fragment
    """
    parsed = urlsplit(url)

    pieces = [
        kwargs.get('scheme', parsed.scheme),
        kwargs.get('netloc', parsed.netloc),
        kwargs.get('path', parsed.path),
    ]
    if kwargs.get('query'):
        pieces.append(urlencode(kwargs['query'], doseq=True))
    else:
        pieces.append(parsed.query)
    pieces.append(kwargs.get('fragment', parsed.fragment))

    return urlunsplit(pieces)


def enum(**enums):
    return type('Enum', (), enums)

def get_youtube_video_id(video_link):
    if re.search('http://www.youtube.com/v/', video_link):
        video_link = re.sub('http://www.youtube.com/v/', '', video_link)
        video_id = video_link.split('?')[0]
        return video_id
    return None


def get_arguments_from_redirect(response):
    "Given a redirect, return the arguments from the location's URL"
    parsed_url = urlsplit(response.headers['location'])
    return {
        # Only return the last value
        key:value[-1]
        for key, value in parse_qs(parsed_url.query).iteritems()
    }

def get_uuid():
    'Return the string representation of a random UUID'
    return str(uuid4())


def meters_to_miles(meters):
    miles = meters * (0.621371 / 1000)
    miles = round(miles, 2)
    return miles


def meters_to_human_readable(meters):
    """Convert meters to human readable format with miles.
    Args:
        meters: int, contains number of meters to convert
    Usage:
        >>> meters_to_human_readable(25000)
        '15.53 miles'
        >>> meters_to_human_readable(0)
        None
    """
    if meters == 0:
        return None
    miles_unit = 'mile'
    miles = meters_to_miles(meters)
    if miles != 1:
        miles_unit += 's'
    return '%.2f %s' % (miles, miles_unit)


def seconds_to_human_readable(seconds):
    """Convert seconds to human readable format with hours and minutes.
    Args:
        seconds: int, contains number of seconds to convert
    Usage:
        >>> seconds_to_human_readable(60*61)
        '1 hour and 1 minute'
        >>> seconds_to_human_readable(0)
        None
    """
    if seconds == 0:
        return None
    hour_unit = 'hour'
    minute_unit = 'minute'
    result = []
    dtime = datetime(1, 1, 1) + timedelta(seconds=seconds)
    if dtime.hour:
        if dtime.hour != 1:
            hour_unit += 's'
        result.append('%d %s' % (dtime.hour, hour_unit))
    if dtime.minute:
        if dtime.minute != 1:
            minute_unit += 's'
        result.append('%d %s' % (dtime.minute, minute_unit))
    return " and ".join(result)


def get_state_abbreviation(state_name):
    """Get state abbreviation from state name.
    Returns:
        A string containing the two letter abbrevitation of the state.
        If the state name is not found, None is returned.
    """
    states = {
        'Alaska': 'AK',
        'Alabama': 'AL',
        'Arkansas': 'AR',
        'American Samoa': 'AS',
        'Arizona': 'AZ',
        'California': 'CA',
        'Colorado': 'CO',
        'Connecticut': 'CT',
        'District of Columbia': 'DC',
        'Delaware': 'DE',
        'Florida': 'FL',
        'Georgia': 'GA',
        'Guam': 'GU',
        'Hawaii': 'HI',
        'Iowa': 'IA',
        'Idaho': 'ID',
        'Illinois': 'IL',
        'Indiana': 'IN',
        'Kansas': 'KS',
        'Kentucky': 'KY',
        'Louisiana': 'LA',
        'Massachusetts': 'MA',
        'Maryland': 'MD',
        'Maine': 'ME',
        'Michigan': 'MI',
        'Minnesota': 'MN',
        'Missouri': 'MO',
        'Northern Mariana Islands': 'MP',
        'Mississippi': 'MS',
        'Montana': 'MT',
        'National': 'NA',
        'North Carolina': 'NC',
        'North Dakota': 'ND',
        'Nebraska': 'NE',
        'New Hampshire': 'NH',
        'New Jersey': 'NJ',
        'New Mexico': 'NM',
        'Nevada': 'NV',
        'New York': 'NY',
        'Ohio': 'OH',
        'Oklahoma': 'OK',
        'Oregon': 'OR',
        'Pennsylvania': 'PA',
        'Puerto Rico': 'PR',
        'Rhode Island': 'RI',
        'South Carolina': 'SC',
        'South Dakota': 'SD',
        'Tennessee': 'TN',
        'Texas': 'TX',
        'Utah': 'UT',
        'Virginia': 'VA',
        'Virgin Islands': 'VI',
        'Vermont': 'VT',
        'Washington': 'WA',
        'Wisconsin': 'WI',
        'West Virginia': 'WV',
        'Wyoming': 'WY',
    }
    try:
        return states[state_name]
    except:
        return None


def build_full_name(first_name, last_name):
    """Build a full name from a first name and last name.
    Args:
        first_name: A string representing the user's first name.
        last_name: A string representing the user's last name.
    Returns:
        A string representing the user's name.
    """
    name = None
    if not first_name and not last_name:
        return None
    if first_name:
        name = first_name
        if last_name:
            name = "%s %s" % (first_name, last_name)
    return name

def basic_authentication_header(username, password):
        """HTTP Basic Auth Header"""
        user_and_pass = "%s:%s" % (username, password)
        encoded = base64.b64encode(user_and_pass)
        return "Basic %s" % encoded
