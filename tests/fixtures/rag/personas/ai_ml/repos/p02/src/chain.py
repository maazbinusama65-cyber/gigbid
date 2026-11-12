from langchain.chains import RetrievalQA
from langchain_pinecone import PineconeVectorStore

def build_chain(llm, index_name: str):
    store = PineconeVectorStore(index_name=index_name)
    return RetrievalQA.from_chain_type(llm, retriever=store.as_retriever(search_kwargs={'k': 4}))

def refuse_if_empty(docs):
    return 'I could not find that in the help centre.' if not docs else None
