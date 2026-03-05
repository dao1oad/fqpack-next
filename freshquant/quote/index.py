from QUANTAXIS import QA_fetch_index_day_adv, QA_fetch_index_min_adv
from freshquant.database.cache import redis_cache

@redis_cache.memoize(expiration=900)
def fq_quote_fetch_index_day_adv(code, start, end):
    data = QA_fetch_index_day_adv(code, start, end)
    if data is not None:
        return data.data
    return

if __name__ == "__main__":
    print(fq_quote_fetch_index_day_adv('000001', '2023-01-01', '2024-08-30'))