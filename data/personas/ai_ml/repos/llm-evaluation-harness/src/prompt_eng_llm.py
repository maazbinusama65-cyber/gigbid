SYSTEM = 'You are a concise assistant. Reply as JSON with keys: summary, next_step.'

def score_llm(llm, text, examples):
    shots = '\n'.join(f'IN: {i}\nOUT: {o}' for i, o in examples)
    return llm(SYSTEM + '\n' + shots + '\nIN: ' + text + '\nOUT:')
