import sys

def instance_or_import(to_import):
    if not isinstance(to_import, basestring):
        return to_import
    return import_(to_import)

def import_(to_import):
    if "." not in to_import:
        return __import__(to_import)
    mod_name, cls_name = to_import.rsplit(".", 1)

    try:
        mod = __import__(mod_name, fromlist=[cls_name])
    except ImportError as e:
        raise ImportError("error importing %r: %s" %(to_import, e)), \
                None, sys.exc_info()[2]
    try:
        result = getattr(mod, cls_name)
    except AttributeError as e:
        raise ImportError("error importing %r: %r" %(to_import, e))
    return result

