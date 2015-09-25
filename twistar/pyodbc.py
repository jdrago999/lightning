from twistar.registry import Registry
from twistar.dbconfig.base import InteractionBase
from twistar.exceptions import ImaginaryTableError, CannotRefreshError

class PyODBCDBConfig(InteractionBase):

    def whereToString(self, where):
        assert(type(where) is list)
        query = where[0] #? will be correct
        args = where[1:]
        return (query, args)


    def updateArgsToString(self, args):
        colnames = self.escapeColNames(args.keys())
        setstring = ",".join([key + " = ?" for key in colnames])
        return (setstring, args.values())


    def insertArgsToString(self, vals):
        return "(" + ",".join(["?" for _ in vals.items()]) + ")"

    def escapeColNames(self, colnames):
        """
        Escape column names for insertion into SQL statement.

        @param colnames: A C{List} of string column names.

        @return: A C{List} of string escaped column names.
        """
        return map(lambda x: "[%s]" % x, colnames)

    def getLastInsertID(self, txn):
        """
        Using the given txn, get the id of the last inserted row.

        @return: The integer id of the last inserted row.
        """
        q = "SELECT SCOPE_IDENTITY()"
        self.executeTxn(txn, q)
        result = txn.fetchall()
        return result[0][0]


    def select(self, tablename, id=None, where=None, group=None, limit=None, orderby=None, select=None):
        """
        Select rows from a table.

        @param tablename: The tablename to select rows from.

        @param id: If given, only the row with the given id will be returned (or C{None} if not found).

        @param where: Conditional of the same form as the C{where} parameter in L{DBObject.find}.

        @param group: String describing how to group results.

        @param limit: Integer limit on the number of results.  If this value is 1, then the result
        will be a single dictionary.  Otherwise, if C{id} is not specified, an array will be returned.
        This can also be a tuple, where the first value is the integer limit and the second value is
        an integer offset.  In the case that an offset is specified, an array will always be returned.

        @param orderby: String describing how to order the results.

        @param select: Columns to select.  Default is C{*}.

        @return: If C{limit} is 1 or id is set, then the result is one dictionary or None if not found.
        Otherwise, an array of dictionaries are returned.
        """
        one = False
        select = select or "*"

        if id is not None:
            where = ["id = ?", id]
            one = True

        if not isinstance(limit, tuple) and limit is not None and int(limit) == 1:
            one = True

	if not isinstance(limit, tuple) and limit is not None:
	   start = "SELECT TOP %s" % limit
	else:
	   start = "SELECT"
        q = "%s %s FROM %s WITH (NOLOCK)" % (start, select, tablename)
        args = []
        if where is not None:
            wherestr, args = self.whereToString(where)
            q += " WHERE " + wherestr
        if group is not None:
            q += " GROUP BY " + group
        if orderby is not None:
            q += " ORDER BY " + orderby

        if isinstance(limit, tuple):
            q += " OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" % (limit[0], limit[1])
        return self.runInteraction(self._doselect, q, args, tablename, one)

    def getSchema(self, tablename, txn=None):
        """
        Get the schema (in the form of a list of column names) for
        a given tablename.  Use the given transaction if specified.
        """
        if not Registry.SCHEMAS.has_key(tablename) and txn is not None:
            try:
                self.executeTxn(txn, "SELECT TOP 1 * FROM %s WITH (NOLOCK)" % tablename)
            except Exception, e:
                raise ImaginaryTableError, "Table %s does not exist." % tablename
            Registry.SCHEMAS[tablename] = [row[0] for row in txn.description]
        return Registry.SCHEMAS.get(tablename, [])

    def count(self, tablename, where=None):
        """
        Get the number of rows in the given table (optionally, that meet the given where criteria).

        @param tablename: The tablename to count rows from.

        @param where: Conditional of the same form as the C{where} parameter in L{DBObject.find}.

        @return: A C{Deferred} that returns the number of rows.
        """
        d = self.select(tablename, where=where, select='count(*)')
        d.addCallback(lambda res: res[0][''])
        return d
