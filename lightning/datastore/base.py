"""
The definition of what any datastore object must adhere to, plus useful methods.
"""

from __future__ import absolute_import

class DatastoreBase(object):
    """
    This is the base class for the datastore used in Lightning.
    """

    def get_oauth_token(self, *args, **kwargs):
        'Abstract base method for get_oauth_token'
        raise NotImplementedError
    def set_oauth_token(self, *args, **kwargs):
        'Abstract base method for set_oauth_token'
        raise NotImplementedError
    def delete_oauth_token(self, *args, **kwargs):
        'Abstract base method for delete_oauth_token'
        raise NotImplementedError

    def get_views(self, *args, **kwargs):
        'Abstract base method for get_views'
        raise NotImplementedError

    def view_exists(self, *args, **kwargs):
        'Abstract base method for view_exists'
        raise NotImplementedError
    def get_view(self, *args, **kwargs):
        'Abstract base method for get_view'
        raise NotImplementedError
    def set_view(self, *args, **kwargs):
        'Abstract base method for set_view'
        raise NotImplementedError
    def delete_view(self, *args, **kwargs):
        'Abstract base method for delete_view'
        raise NotImplementedError

    def get_most_recent_key(self, *args, **kwargs):
        'Abstract base method for get_most_recent_key'
        raise NotImplementedError
    def get_value(self, *args, **kwargs):
        'Abstract base method for get_value'
        raise NotImplementedError
    def get_value_range(self, *args, **kwargs):
        'Abstract base method for get_value_range'
        raise NotImplementedError
    def is_duplicate_value(self, *args, **kwargs):
        'Abstract base method for is_duplicate_value'
        raise NotImplementedError
    def write_value(self, *args, **kwargs):
        'Abstract base method for write_value'
        raise NotImplementedError
