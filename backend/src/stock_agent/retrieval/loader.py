from pathlib import Path

from langchain_core.documents import Document


def load_text_file(path: Path, company_id) -> Document:
    text = path.read_text(encoding="utf-8")

    return Document(
        page_content=path.read_text(encoding="utf-8"),
        metadata={
            "source": str(path),
            "company_id": company_id,
        },
    )


documents = [
    load_text_file(
        Path("backend/fixtures/data/nvda.txt"),
        "NVDA",
    ),
    load_text_file(
        Path("backend/fixtures/data/amd.txt"),
        "AMD",
    ),
]

# for document in documents:
#     print(document.metadata)
#     print(document.page_content)