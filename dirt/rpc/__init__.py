def status(): # XXX fix up (add "return"?), move out of __init__
    [            
        pool.summarize()
        for pool in ConnectionPool.active_pools.values()
    ]

def connection_handler(call_handler):
    pass


