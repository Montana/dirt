def instance_or_import(to_import):
    if not isinstance(to_import, basestring):
        return to_import
    return import_(to_import)

def import_(to_import):
    if "." not in to_import:
        return __import__(to_import)
    mod_name, cls_name = to_import.rsplit(".", 1)
    mod = __import__(mod_name, fromlist=[cls_name])
    return getattr(mod, cls_name)
