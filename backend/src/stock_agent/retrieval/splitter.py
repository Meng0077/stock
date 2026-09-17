from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

def split_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=150,
        chunk_overlap=50,
    )
    chunks = []
    for document in documents:
        document_chunks = splitter.split_documents(
            [document]
        )

        source = Path( document.metadata["source"]).name
        company_id = document.metadata["company_id"]

        for index, chunk in enumerate(document_chunks):

            chunk.metadata["evidence_id"] = (
                f"rag:{company_id}:{source}:{index}"
            )

        chunks.extend(document_chunks)
    return chunks


if __name__ == "__main__":

    from stock_agent.retrieval.loader import load_text_file

    document = load_text_file(Path("backend/fixtures/data/nvda.txt"), "NVDA")
    chunks = split_documents([document])
    for chunk in chunks:
        print(chunk.metadata)
        print(chunk.page_content)
        print('_______________')
