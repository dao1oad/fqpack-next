from freshquant.carnation.param import queryParam
from freshquant.database.cache import in_memory_cache

@in_memory_cache.memoize(expiration=900)
def getTdxhqEndpoint():
    return queryParam('tdx.hq.endpoint', '127.0.0.1:5001')
