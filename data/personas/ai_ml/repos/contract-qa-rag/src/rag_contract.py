def run_contract(question, retriever, llm):
    ctx = retriever.search(question, k=5)
    prompt = 'Answer using only these sources:\n' + '\n'.join(c['text'] for c in ctx)
    return llm(prompt + '\nQ: ' + question), [c['id'] for c in ctx]
