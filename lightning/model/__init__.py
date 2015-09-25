from twistar.dbobject import DBObject


class DatastoreModel(DBObject):

    def to_dict(self, without=None):
        if not self:
            return None
        keys = ['_config', '_deleted', 'id', 'errors']
        if without and isinstance(without, list):
            keys.extend(without)
        vals = self.__dict__
        # Remove vals used by twistar DBObject
        for x in keys:
            if x in vals:
                del vals[x]
        return vals

class LimitedDict(dict):
    """LimitedDict class.
    This class implements a dictionary whose initial keys are limited.
    """
    def __init__(self, keys, **kwargs):
        # Ensure that only these keys are always present in the object,
        # default any value that is not found or empty string to None.
        args = {}
        for k in keys:
            args[k] = kwargs.get(k, None)
            if args[k] == "":
                args[k] = None
        dict.__init__(self, args)