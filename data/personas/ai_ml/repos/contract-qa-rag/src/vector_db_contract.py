from pinecone import Pinecone

pc = Pinecone(api_key='...')
index = pc.Index('contract_qa_rag')

def route_contract(vec, industry):
    return index.query(vector=vec, top_k=8, filter={'industry': industry})
