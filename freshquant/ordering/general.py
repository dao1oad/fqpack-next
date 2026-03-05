import base62

from bson import ObjectId

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant


@in_memory_cache.memoize(expiration=864000)
def query_strategy_id(code: str) -> str:
    strategy = DBfreshquant["strategies"].find_one({"code": code})
    id = ObjectId()
    if strategy is not None:
        id = strategy["_id"]
    b62Uid = base62.encodebytes(id.binary)
    if strategy is not None and strategy.get("b62_uid") != b62Uid:
        DBfreshquant["strategies"].update_one(
            {"_id": id}, {"$set": {"b62_uid": b62Uid}}
        )
    return b62Uid


if __name__ == "__main__":
    id = ObjectId()
    print(id)
    print(id.binary)
    b62Uid = base62.encodebytes(id.binary)
    print(b62Uid)
    print(base62.decodebytes(b62Uid))
    print(ObjectId(base62.decodebytes(b62Uid)))
    

