import redis

r = redis.Redis()

def score_product(key, compute, ttl=300):
    hit = r.get(key)
    if hit is not None:
        return hit
    val = compute()
    r.setex(key, ttl, val)
    return val
