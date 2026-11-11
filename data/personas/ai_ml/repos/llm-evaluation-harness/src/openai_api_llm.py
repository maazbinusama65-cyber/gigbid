from openai import OpenAI

client = OpenAI()

def load_llm(prompt):
    r = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': prompt}], temperature=0.2)
    return r.choices[0].message.content
