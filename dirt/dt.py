import calendar
from datetime import datetime

import pytz

def utcnow():
    return datetime.utcnow()

def localnow(timezone):
    """ Returns a naive (ie, sans-timezone) datetime which represents the
        current time in ``timezone``. """
    return localfromutc(utcnow(), timezone)

def utcfromlocal(local_dt, timezone):
    if timezone is not None:
        local_dt = timezone.localize(local_dt)
    utc_dt = local_dt.astimezone(pytz.utc)
    return utc_dt.replace(tzinfo=None)

def localfromutc(utc_dt, timezone):
    utc_dt = utc_dt.replace(tzinfo=pytz.utc)
    local_dt = timezone.normalize(utc_dt.astimezone(timezone))
    return local_dt.replace(tzinfo=None)

def utcfromtimestamp(timestamp):
    """ Returns a datetime from UTC timestamp ``timestamp``.

        >>> utcfromtimestamp(1234.5)
        datetime.datetime(1970, 1, 1, 0, 20, 34, 500000)
        >>> """
    return datetime.utcfromtimestamp(timestamp)

def timestampfromutc(dt):
    """ Returns a timestamp from UTC datetime ``dt``.

        >>> timestampfromutc(datetime(1970, 1, 1, 0, 20, 34, 500000))
        1234.5
        >>> """
    return calendar.timegm(dt.utctimetuple()) + (dt.microsecond / 1000000.0)

def utcfromiso(dt):
    return datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S.%fZ")

def isofromutc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def isofromlocal(dt, timezone, **is_dst):
    return timezone.localize(dt, **is_dst).isoformat()
