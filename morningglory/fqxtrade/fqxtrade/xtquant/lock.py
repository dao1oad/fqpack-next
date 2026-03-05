from contextlib import contextmanager
import uuid
from loguru import logger
from fqxtrade.database.redis import redis_db

@contextmanager
def redis_distributed_lock(lock_key, expire_time=10000):
    """Redis分布式锁上下文管理器"""
    lock_value = str(uuid.uuid4())
    acquired = redis_db.set(lock_key, lock_value, nx=True, px=expire_time)
    try:
        if acquired:
            yield True
        else:
            logger.warning(f"获取分布式锁失败: {lock_key}")
            yield False
    finally:
        if acquired:
            lua_script = """
                if redis.call("get",KEYS[1]) == ARGV[1] then
                    return redis.call("del",KEYS[1])
                else
                    return 0
                end
            """
            redis_db.eval(lua_script, 1, lock_key, lock_value)