import redis
from pydash import get

from freshquant.config import settings

host = get(settings, 'redis.host', '127.0.0.1')
port = get(settings, 'redis.port', 6379)
db = get(settings, 'redis.db', 1)
password = get(settings, 'redis.password')

redis_connection_pool = redis.ConnectionPool(host=host, port=port, db=db, password=password, decode_responses=True)
redis_db = redis.StrictRedis(connection_pool=redis_connection_pool)
