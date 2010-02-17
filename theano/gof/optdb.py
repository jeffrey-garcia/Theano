import sys, StringIO

if sys.version_info[:2] >= (2,5):
  from collections import defaultdict
else:
  from python25 import defaultdict

import opt


class DB(object):
    def __hash__(self):
        if not hasattr(self, '_optimizer_idx'):
            self._optimizer_idx = opt._optimizer_idx[0]
            opt._optimizer_idx[0] += 1
        return self._optimizer_idx

    def __init__(self):
        self.__db__ = defaultdict(set)
        self._names = set()
        self.name = None #will be reset by register 
        #(via obj.name by the thing doing the registering)

    def register(self, name, obj, *tags):
        # N.B. obj is not an instance of class Optimizer.
        # It is an instance of a DB.In the tests for example,
        # this is not always the case.
        if not isinstance(obj, (DB, opt.Optimizer, opt.LocalOptimizer)):
            raise Exception('wtf', obj)
            
        if self.name is not None:
            tags = tags + (self.name,)
        obj.name = name
        if name in self.__db__:
            raise ValueError('The name of the object cannot be an existing tag or the name of another existing object.', obj, name)
        self.__db__[name] = set([obj])
        self._names.add(name)

        self.add_tags(name, *tags)
          
    def add_tags(self, name, *tags):
        obj = self.__db__[name]
        assert len(obj)==1
        obj = obj.copy().pop()
        for tag in tags:
            if tag in self._names:
                raise ValueError('The tag of the object collides with a name.', obj, tag)
            self.__db__[tag].add(obj)

    def __query__(self, q):
        if not isinstance(q, Query):
            raise TypeError('Expected a Query.', q)
        variables = set()
        for tag in q.include:
            variables.update(self.__db__[tag])
        for tag in q.require:
            variables.intersection_update(self.__db__[tag])
        for tag in q.exclude:
            variables.difference_update(self.__db__[tag])
        remove = set()
        add = set()
        for obj in variables:
            if isinstance(obj, DB):
                sq = q.subquery.get(obj.name, q)
                if sq:
                    replacement = obj.query(sq)
                    replacement.name = obj.name
                    remove.add(obj)
                    add.add(replacement)
        variables.difference_update(remove)
        variables.update(add)
        return variables

    def query(self, *tags, **kwtags):
        if len(tags) >= 1 and isinstance(tags[0], Query):
            if len(tags) > 1 or kwtags:
                raise TypeError('If the first argument to query is a Query, there should be no other arguments.', tags, kwtags)
            return self.__query__(tags[0])
        include = [tag[1:] for tag in tags if tag.startswith('+')]
        require = [tag[1:] for tag in tags if tag.startswith('&')]
        exclude = [tag[1:] for tag in tags if tag.startswith('-')]
        if len(include) + len(require) + len(exclude) < len(tags):
            raise ValueError("All tags must start with one of the following characters: '+', '&' or '-'", tags)
        return self.__query__(Query(include = include,
                                    require = require,
                                    exclude = exclude,
                                    subquery = kwtags))

    def __getitem__(self, name):
        variables = self.__db__[name]
        if not variables:
            raise KeyError("Nothing registered for '%s'" % name)
        elif len(variables) > 1:
            raise ValueError('More than one match for %s (please use query)' % name)
        for variable in variables:
            return variable

    def print_summary(self, stream=sys.stdout):
        print >> stream, "%s (id %i)"%(self.__class__.__name__, id(self))
        print >> stream, "  names", self._names
        print >> stream, "  db", self.__db__


class Query(object):

    def __init__(self, include, require = None, exclude = None, subquery = None):
        self.include = set(include)
        self.require = require or set()
        self.exclude = exclude or set()
        self.subquery = subquery or {}

    #add all opt with this tag
    def including(self, *tags):
        return Query(self.include.union(tags),
                     self.require,
                     self.exclude,
                     self.subquery)
    #remove all opt with this tag
    def excluding(self, *tags):
        return Query(self.include,
                     self.require,
                     self.exclude.union(tags),
                     self.subquery)
    #keep only opt with this tag.
    def requiring(self, *tags):
        return Query(self.include,
                     self.require.union(tags),
                     self.exclude,
                     self.subquery)




class EquilibriumDB(DB):
    """A set of potential optimizations which should be applied in an arbitrary order until
    equilibrium is reached.

    Canonicalize, Stabilize, and Specialize are all equilibrium optimizations.

    .. note::
        
        It seems like this might be supposed to contain LocalOptimizer instances rather than
        optimizer instances, because whatever is selected by the query is passed to
        EquilibriumOptimizer and EquilibriumOptimizer requires LocalOptimizer instances.

    """

    def query(self, *tags, **kwtags):
        opts = super(EquilibriumDB, self).query(*tags, **kwtags)
        return opt.EquilibriumOptimizer(opts, 
                max_depth=5,
                max_use_ratio=10,
                failure_callback=opt.NavigatorOptimizer.warn_inplace)


class SequenceDB(DB):
    """A sequence of potential optimizations.

    Retrieve a sequence of optimizations (a SeqOptimizer) by calling query().

    Each potential optimization is registered with a floating-point position.
    No matter which optimizations are selected by a query, they are carried out in order of
    increasing position.

    The optdb itself (`theano.compile.mode.optdb`), from which (among many other tags) fast_run
    and fast_compile optimizers are drawn is a SequenceDB.

    """

    def __init__(self, failure_callback = opt.SeqOptimizer.warn):
        super(SequenceDB, self).__init__()
        self.__position__ = {}
        self.failure_callback = failure_callback

    def register(self, name, obj, position, *tags):
        super(SequenceDB, self).register(name, obj, *tags)
        self.__position__[name] = position

    def query(self, *tags, **kwtags):
        """
        :type position_cutoff: float or int
        :param position_cutoff: only optimizations with position less than the cutoff are returned.
        """
        position_cutoff = kwtags.pop('position_cutoff', float('inf'))
        opts = super(SequenceDB, self).query(*tags, **kwtags)
        opts = [o for o in opts if self.__position__[o.name] < position_cutoff]
        opts.sort(key = lambda obj: self.__position__[obj.name])
        return opt.SeqOptimizer(opts, failure_callback = self.failure_callback)

    def print_summary(self, stream=sys.stdout):
        print >> stream, "SequenceDB (id %i)"%id(self)
        print >> stream, "  position", self.__position__
        print >> stream, "  names", self._names
        print >> stream, "  db", self.__db__

    def __str__(self):
        sio = StringIO.StringIO()
        self.print_summary(sio)
        return sio.getvalue()


