from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([('system', 'Be concise.'), ('human', '{q}')])

def route_sales(llm, q):
    return (prompt | llm).invoke({'q': q})
