from fastapi.testclient import TestClient

from app import app, semantic_scholar_paper
from formatters import citation_key, format_gbt7714, format_items


def sample():
    return {
        "title": "A Study & More",
        "authors": ["张三", "李四", "王五", "赵六"],
        "year": 2024,
        "venue": "测试期刊",
        "volume": "12",
        "issue": "3",
        "pages": "10-20",
        "doi": "10.1234/example",
        "url": "https://example.com/paper",
        "type": "article",
    }


def test_formatters_cover_expected_styles():
    item = sample()
    assert citation_key(item).startswith("2024") is False
    assert "\\&" in format_items([item], "bibtex")[0]
    assert "等" in format_gbt7714(item)
    assert "10.1234/example" in format_items([item], "apa")[0]
    assert "TY  - JOUR" in format_items([item], "ris")[0]
    assert "[1]" in format_items([item], "ieee")[0]


def test_semantic_scholar_record_mapping():
    paper = semantic_scholar_paper(
        {
            "paperId": "s2-id",
            "title": "Attention Is All You Need",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
            "year": 2017,
            "venue": "NeurIPS",
            "publicationVenue": {"name": "Neural Information Processing Systems"},
            "publicationTypes": ["Conference"],
            "externalIds": {"DOI": "10.48550/ARXIV.1706.03762", "ArXiv": "1706.03762"},
            "url": "https://www.semanticscholar.org/paper/s2-id",
            "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762"},
            "journal": {"volume": "30", "pages": "5998-6008"},
        },
        "Attention Is All You Need",
    )

    assert paper is not None
    assert paper.sources == ["Semantic Scholar"]
    assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper.venue == "Neural Information Processing Systems"
    assert paper.volume == "30"
    assert paper.pages == "5998-6008"
    assert paper.doi == "10.48550/arxiv.1706.03762"
    assert paper.url == "https://doi.org/10.48550/arxiv.1706.03762"


def test_health_and_invalid_format():
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.post("/api/format", json={"items": [sample()], "format": "unknown"})
    assert response.status_code == 400


def test_reject_non_pdf_upload():
    client = TestClient(app)
    response = client.post("/api/pdf", files={"file": ("note.txt", b"hello", "text/plain")})
    assert response.status_code == 400
