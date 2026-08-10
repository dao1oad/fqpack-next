import logging

from freshquant.carnation.param import queryParam
from freshquant.database.cache import in_memory_cache

logger = logging.getLogger(__name__)

GATEWAY_DEFAULT_TDXHQ_ENDPOINT = "127.0.0.1:5001"


@in_memory_cache.memoize(expiration=900)
def getTdxhqEndpoint():
    endpoint = queryParam("tdx.hq.endpoint", GATEWAY_DEFAULT_TDXHQ_ENDPOINT)
    if not endpoint or str(endpoint).strip() == GATEWAY_DEFAULT_TDXHQ_ENDPOINT:
        logger.warning(
            "getTdxhqEndpoint falling back to default %s; configure param "
            "tdx.hq.endpoint (prefer env FRESHQUANT_TDX__HQ_ENDPOINT in compose)",
            GATEWAY_DEFAULT_TDXHQ_ENDPOINT,
        )
    return endpoint
