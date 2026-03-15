import redis

from freshquant.bootstrap_config import bootstrap_config

host = bootstrap_config.redis.host
port = bootstrap_config.redis.port
db = bootstrap_config.redis.db
password = bootstrap_config.redis.password or None

redis_connection_pool = redis.ConnectionPool(
    host=host, port=port, db=db, password=password, decode_responses=True
)
redis_db = redis.StrictRedis(connection_pool=redis_connection_pool)
