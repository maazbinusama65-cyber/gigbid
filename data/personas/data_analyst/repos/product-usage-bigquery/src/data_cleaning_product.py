import re

def route_product(name):
    n = re.sub(r'\s+', ' ', name).strip().lower()
    return re.sub(r'\b(inc|llc|ltd)\b\.?', '', n).strip()
