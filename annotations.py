import warnings
import inspect
import functools
import time
import sys, os

def deprecated(*args, **kwargs):
    """"
    Decorator to mark a method or class as deprecated
    """
    def __wrapper_deprecated(method):
        @functools.wraps(method)
        def deprecatedwarning(*ar, **kw):
            if inspect.isclass(method):
                fmt1 = "Call to deprecated class:{} (()})"
            else:
                fmt1 = "Call to deprecated function: {} ({})"
            warnings.simplefilter('always', DeprecationWarning)
            warnings.warn(
                fmt1.format(method.__name__, kwargs.get("reason", "")),
                category = DeprecationWarning,
                stacklevel = 2 
            )
            return method(*ar, **kw)  
        return deprecatedwarning
    
    if (len(args) == 1 and len(kwargs) == 0 and callable(args[0])):
        return __wrapper_deprecated(args[0])
    else:
        return __wrapper_deprecated
    
class StdoutBlocker(object):
    """
    Use as:
    
        with StdoutBlocker():
            pass
    
    to temporarily block all printing to the command line
    """
    def __init__(self):
        self.old_stdout = None
    
    def __enter__(self):
        self.old_stdout = sys.stdout # backup current stdout
        sys.stdout = open(os.devnull, "w")
    
    def __exit__(self, type, value, traceback):
        sys.stdout.flush()
        sys.stdout.close()
        sys.stdout = self.old_stdout # reset old stdout
        self.old_stdout = None

def timeit(*args, **kwargs):
    """
        Function timer decorator
    """    
    unit = kwargs.get('unit', 'ms')
    include_time = kwargs.get('include_time', False)
    
    def __wrapper_timeit(method):
        @functools.wraps(method)
        def timefunction(*ar, **kw):
            ts = time.time()
            result = method(*ar, **kw)
            te = time.time()
            mtime = (te-ts)
        
            if (unit in ["ms", "milli", "millisec", "milliseconds"]):
                mtime *= 1000
            elif (unit in ["s", "sec", "seconds"]):
                pass
            elif (unit in ["m", "min", "minutes"]):
                mtime /= 60
            elif (unit in ["h", "hours"]):
                mtime /= (60*60)
            else:
                raise ValueError("Unknown time unit")
            
            print('@timeit \"{:s}\": {:2.2f}{}'.format(kwargs.get('log_name', method.__name__), mtime, unit))
            return result 
        
        def silent(*ar, **kw):
            return method(*ar, **kw)
        
        timefunction.silent = silent
        
        return timefunction

    if (len(args) == 1 and len(kwargs) == 0 and callable(args[0])):
        return __wrapper_timeit(args[0])
    else:
        return __wrapper_timeit
    
@deprecated
def timeit_proxy(*args, **kwargs):
    """
        Function timer decorator 
        Allows proxying function decorator calls e.g.
            @timeit()
            @functools.lru_cache()
            def somefunc():
                pass
            
            somefunc.cache_info()
    """
    class __wrapper_timeit_proxy():
        """
            Decriptor class
        """
        def __init__(self, method):
            self.method = method
            self.name = kwargs.get('log_name', self.method.__name__)
        
        def __call__(self, *ar, **kw):
            ts = time.time()
            result = self.method(*ar, **kw)
            te = time.time()
            print('@timeit \"{:s}\": {:2.2f}ms'.format(self.name, (te-ts)*1000))
            return result   

        def __getattr__(self, attr):
            # proxy
            return getattr(self.method, attr)
        
        def __get__(self, instance, owner):
            return functools.partial(self.__call__, instance)
    
        def __repr__(self):
            return "@timeit decorator for: "+ self.name
    
    if (len(args) == 1 and len(kwargs) == 0 and callable(args[0])):
        return __wrapper_timeit_proxy(args[0])
    else:
        return __wrapper_timeit_proxy