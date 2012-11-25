
def status():
    [            
        pool.summarize()
        for pool in ConnectionPool.active_pools.values()
    ]

def connection_handler(call_handler):
    pass


