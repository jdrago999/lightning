#!/usr/bin/env python

import logging
import os
import pprint
import sys

sys.path.append(os.path.dirname(__file__) + '/..')

from lightning.service.facebook import Facebook

logging.warning("Save this password since we only see it once: %s"
    % pprint.pformat(Facebook().generate_test_user('John Doe')))
