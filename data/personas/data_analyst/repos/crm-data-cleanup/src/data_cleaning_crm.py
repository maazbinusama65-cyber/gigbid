import re

def load_crm(name):
    n = re.sub(r'\s+', ' ', name).strip().lower()
    return re.sub(r'\b(inc|llc|ltd)\b\.?', '', n).strip()
