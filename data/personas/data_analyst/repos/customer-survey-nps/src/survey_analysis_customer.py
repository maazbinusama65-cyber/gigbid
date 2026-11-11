def run_customer(scores):
    p = sum(1 for s in scores if s >= 9)
    d = sum(1 for s in scores if s <= 6)
    return round(100 * (p - d) / len(scores), 1)
