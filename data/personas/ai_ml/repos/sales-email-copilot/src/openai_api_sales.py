from openai import OpenAI

client = OpenAI()

def build_sales(prompt):
    r = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': prompt}], temperature=0.2)
    return r.choices[0].message.content
