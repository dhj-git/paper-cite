import asyncio
import io
import os
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote
from xml.etree import ElementTree

import fitz
import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from formatters import FORMATS, format_items

BASE_DIR = Path(__file__).resolve().parent
USER_AGENT = "paper-cite/0.1 (local academic citation tool; mailto:paper-cite@example.invalid)"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_FIELDS = "paperId,title,authors,year,venue,publicationVenue,publicationTypes,externalIds,url,openAccessPdf,journal"
MAX_PDF_SIZE = 15 * 1024 * 1024
MAX_BATCH_FILES = 50
MAX_BATCH_SIZE = 250 * 1024 * 1024
BATCH_CONCURRENCY = 3
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
ARXIV_RE = re.compile(r"(?:arxiv:\s*)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7})(?:\.pdf)?", re.I)
PMID_RE = re.compile(r"(?:pmid:\s*)?(\d{6,9})$", re.I)


class Paper(BaseModel):
    id: str = ""
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    type: str = "article"
    doi: str = ""
    url: str = ""
    source_url: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[Paper]
    source_status: dict[str, str]
    extracted: dict[str, Any] | None = None


class FormatRequest(BaseModel):
    items: list[Paper]
    format: str


class BatchItem(BaseModel):
    filename: str
    status: str = "pending"
    query: str = ""
    results: list[Paper] = Field(default_factory=list)
    source_status: dict[str, str] = Field(default_factory=dict)
    extracted: dict[str, Any] | None = None
    error: str = ""


class BatchStatus(BaseModel):
    batch_id: str
    status: str = "pending"
    total: int
    completed: int = 0
    failed: int = 0
    items: list[BatchItem]


BATCHES: dict[str, BatchStatus] = {}
RUNNING_BATCHES: set[asyncio.Task[None]] = set()


app = FastAPI(title="Paper Cite", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def clean_doi(value: str) -> str:
    match = DOI_RE.search(value or "")
    return match.group(0).rstrip(".,;)]}").lower() if match else ""


def year_from(value: Any) -> int | None:
    try:
        if isinstance(value, list):
            value = value[0][0]
        year = int(value)
        return year if 1000 <= year <= 3000 else None
    except (TypeError, ValueError, IndexError):
        return None


def paper_id(doi: str, title: str) -> str:
    import hashlib
    return hashlib.sha1((doi or re.sub(r"\W", "", title.lower())).encode()).hexdigest()[:12]


def normalize_title(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]", "", value.lower())


def confidence(query: str, title: str, doi: str = "") -> float:
    query_doi = clean_doi(query)
    if query_doi and query_doi == clean_doi(doi):
        return 1.0
    q = set(normalize_title(query))
    t = set(normalize_title(title))
    return round(min(0.99, 0.45 + 0.54 * len(q & t) / max(len(q | t), 1)), 2)


def make_paper(*, source: str, query: str, title: str, authors: list[str], year: int | None, venue: str = "", volume: str = "", issue: str = "", pages: str = "", publisher: str = "", kind: str = "article", doi: str = "", url: str = "", source_url: str = "") -> Paper:
    doi = clean_doi(doi)
    return Paper(id=paper_id(doi, title), title=title.strip(), authors=authors, year=year, venue=venue, volume=volume, issue=issue, pages=pages, publisher=publisher, type=kind, doi=doi, url=url or (f"https://doi.org/{doi}" if doi else ""), source_url=source_url, sources=[source], confidence=confidence(query, title, doi))


async def search_crossref(client: httpx.AsyncClient, query: str) -> list[Paper]:
    doi = clean_doi(query)
    endpoint = f"https://api.crossref.org/works/{quote(doi, safe='')}" if doi else "https://api.crossref.org/works"
    params = None if doi else {"query.bibliographic": query, "rows": 6, "select": "DOI,title,author,published,container-title,volume,issue,page,publisher,type,URL"}
    response = await client.get(endpoint, params=params)
    response.raise_for_status()
    message = response.json()["message"]
    records = [message] if doi else message.get("items", [])
    result = []
    for record in records:
        title = (record.get("title") or [""])[0]
        if not title:
            continue
        authors = [" ".join(part for part in [a.get("given", ""), a.get("family", "")] if part).strip() for a in record.get("author", [])]
        result.append(make_paper(source="Crossref", query=query, title=title, authors=authors, year=year_from((record.get("published") or {}).get("date-parts")), venue=(record.get("container-title") or [""])[0], volume=record.get("volume", ""), issue=record.get("issue", ""), pages=record.get("page", ""), publisher=record.get("publisher", ""), kind=record.get("type", "article"), doi=record.get("DOI", ""), url=record.get("URL", ""), source_url=f"https://api.crossref.org/works/{quote(record.get('DOI', ''), safe='')}") )
    return result


async def search_openalex(client: httpx.AsyncClient, query: str) -> list[Paper]:
    doi = clean_doi(query)
    params = {"filter": f"doi:https://doi.org/{doi}", "per-page": 6} if doi else {"search": query, "per-page": 6}
    response = await client.get("https://api.openalex.org/works", params=params)
    response.raise_for_status()
    result = []
    for record in response.json().get("results", []):
        title = record.get("title") or ""
        if not title:
            continue
        location = record.get("primary_location") or {}
        source = location.get("source") or {}
        biblio = record.get("biblio") or {}
        pages = "-".join(str(value) for value in [biblio.get("first_page"), biblio.get("last_page")] if value)
        authors = [(entry.get("author") or {}).get("display_name", "") for entry in record.get("authorships", [])]
        result.append(make_paper(source="OpenAlex", query=query, title=title, authors=[a for a in authors if a], year=year_from(record.get("publication_year")), venue=source.get("display_name", ""), volume=biblio.get("volume") or "", issue=biblio.get("issue") or "", pages=pages, publisher=source.get("host_organization_name", ""), kind=record.get("type", "article"), doi=record.get("doi", ""), url=location.get("landing_page_url") or record.get("doi", ""), source_url=record.get("id", "")))
    return result


def semantic_scholar_paper(record: dict[str, Any], query: str) -> Paper | None:
    title = record.get("title") or ""
    if not title:
        return None
    external_ids = record.get("externalIds") or {}
    publication_venue = record.get("publicationVenue") or {}
    journal = record.get("journal") or {}
    publication_types = record.get("publicationTypes") or []
    paper_url = record.get("url") or ""
    doi = external_ids.get("DOI", "")
    return make_paper(
        source="Semantic Scholar",
        query=query,
        title=title,
        authors=[author.get("name", "") for author in record.get("authors", []) if author.get("name")],
        year=year_from(record.get("year")),
        venue=publication_venue.get("name") or record.get("venue") or journal.get("name") or "",
        volume=journal.get("volume") or "",
        pages=journal.get("pages") or "",
        publisher=publication_venue.get("publisher") or "",
        kind=publication_types[0] if publication_types else "article",
        doi=doi,
        url="" if doi else paper_url,
        source_url=paper_url,
    )


async def search_semantic_scholar(client: httpx.AsyncClient, query: str) -> list[Paper]:
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    headers = {"x-api-key": api_key} if api_key else None
    doi = clean_doi(query)
    arxiv = ARXIV_RE.fullmatch(query.strip())
    identifier = f"DOI:{doi}" if doi else f"ARXIV:{arxiv.group(1).split('v')[0]}" if arxiv else ""

    if identifier:
        response = await client.get(
            f"{SEMANTIC_SCHOLAR_API_URL}/paper/{quote(identifier, safe=':')}",
            params={"fields": SEMANTIC_SCHOLAR_FIELDS},
            headers=headers,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        records = [response.json()]
    else:
        response = await client.get(
            f"{SEMANTIC_SCHOLAR_API_URL}/paper/search",
            params={"query": query, "limit": 6, "fields": SEMANTIC_SCHOLAR_FIELDS},
            headers=headers,
        )
        response.raise_for_status()
        records = response.json().get("data", [])

    papers = [semantic_scholar_paper(record, query) for record in records]
    return [paper for paper in papers if paper is not None]


async def search_arxiv(client: httpx.AsyncClient, query: str) -> list[Paper]:
    match = ARXIV_RE.search(query.strip())
    expression = f"id:{match.group(1).split('v')[0]}" if match else f'all:"{query}"'
    response = await client.get("https://export.arxiv.org/api/query", params={"search_query": expression, "start": 0, "max_results": 6})
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    result = []
    for entry in root.findall("a:entry", ns):
        title = " ".join((entry.findtext("a:title", "", ns)).split())
        authors = [node.findtext("a:name", "", ns) for node in entry.findall("a:author", ns)]
        published = entry.findtext("a:published", "", ns)
        arxiv_url = entry.findtext("a:id", "", ns)
        doi = entry.findtext("arxiv:doi", "", ns)
        result.append(make_paper(source="arXiv", query=query, title=title, authors=authors, year=year_from(published[:4]), venue="arXiv", kind="preprint", doi=doi, url=arxiv_url, source_url=arxiv_url))
    return result


async def search_pubmed(client: httpx.AsyncClient, query: str) -> list[Paper]:
    pmid = PMID_RE.fullmatch(query.strip())
    ids: list[str]
    if pmid:
        ids = [pmid.group(1)]
    else:
        search = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params={"db": "pubmed", "term": query, "retmode": "json", "retmax": 6})
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    response = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    response.raise_for_status()
    payload = response.json().get("result", {})
    result = []
    for uid in ids:
        record = payload.get(uid, {})
        article_ids = {entry.get("idtype"): entry.get("value") for entry in record.get("articleids", [])}
        result.append(make_paper(source="PubMed", query=query, title=record.get("title", ""), authors=[a.get("name", "") for a in record.get("authors", [])], year=year_from((record.get("pubdate") or "")[:4]), venue=record.get("fulljournalname") or record.get("source", ""), volume=record.get("volume", ""), issue=record.get("issue", ""), pages=record.get("pages", ""), kind="journal-article", doi=article_ids.get("doi", ""), url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}/", source_url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"))
    return [paper for paper in result if paper.title]


SOURCES: dict[str, Callable[[httpx.AsyncClient, str], Awaitable[list[Paper]]]] = {
    "Crossref": search_crossref,
    "OpenAlex": search_openalex,
    "Semantic Scholar": search_semantic_scholar,
    "arXiv": search_arxiv,
    "PubMed": search_pubmed,
}


def deduplicate(papers: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    for paper in papers:
        key = f"doi:{paper.doi}" if paper.doi else f"title:{normalize_title(paper.title)}"
        if key in merged:
            current = merged[key]
            current.sources = list(dict.fromkeys(current.sources + paper.sources))
            current.confidence = max(current.confidence, paper.confidence)
            for field in ("venue", "volume", "issue", "pages", "publisher", "doi", "url", "source_url"):
                if not getattr(current, field) and getattr(paper, field):
                    setattr(current, field, getattr(paper, field))
            if len(paper.authors) > len(current.authors):
                current.authors = paper.authors
        else:
            merged[key] = paper
    return sorted(merged.values(), key=lambda paper: paper.confidence, reverse=True)


async def perform_search(query: str) -> tuple[list[Paper], dict[str, str]]:
    timeout = httpx.Timeout(12.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml, application/xml"}, follow_redirects=True) as client:
        responses = await asyncio.gather(*(function(client, query) for function in SOURCES.values()), return_exceptions=True)
    papers: list[Paper] = []
    status: dict[str, str] = {}
    for name, response in zip(SOURCES, responses):
        if isinstance(response, BaseException):
            status[name] = f"失败: {type(response).__name__}"
        else:
            papers.extend(response)
            status[name] = f"成功 ({len(response)})"
    return deduplicate(papers), status


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/search", response_model=SearchResponse)
async def search(q: str = Query(min_length=2, max_length=500)) -> SearchResponse:
    results, status = await perform_search(q.strip())
    return SearchResponse(query=q, results=results, source_status=status)


def extract_pdf_data(data: bytes, filename: str | None) -> dict[str, Any]:
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "文件不是有效的 PDF")
    try:
        with fitz.open(stream=io.BytesIO(data), filetype="pdf") as document:
            if document.page_count == 0:
                raise HTTPException(400, "PDF 没有页面")
            metadata = document.metadata or {}
            first_page = document[0].get_text("text")[:12000]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "无法解析 PDF") from exc

    doi = clean_doi(first_page) or clean_doi(str(metadata.get("subject", "")))
    title = str(metadata.get("title") or "").strip()
    if not title or title.lower() in {"untitled", "microsoft word"}:
        lines = [line.strip() for line in first_page.splitlines() if 15 <= len(line.strip()) <= 300]
        title = lines[0] if lines else ""
    query = doi or title
    if not query:
        raise HTTPException(422, "未能从 PDF 提取 DOI 或标题")
    return {
        "query": query,
        "filename": filename,
        "title": title,
        "doi": doi,
        "metadata": {key: metadata.get(key, "") for key in ("author", "subject", "keywords")},
    }


@app.post("/api/pdf", response_model=SearchResponse)
async def parse_pdf(file: UploadFile = File(...)) -> SearchResponse:
    data = await file.read(MAX_PDF_SIZE + 1)
    if len(data) > MAX_PDF_SIZE:
        raise HTTPException(413, "PDF 不能超过 15 MB")
    extracted = await asyncio.to_thread(extract_pdf_data, data, file.filename)
    results, status = await perform_search(extracted["query"])
    return SearchResponse(query=extracted["query"], results=results, source_status=status, extracted={key: value for key, value in extracted.items() if key != "query"})


async def process_pdf_batch(batch_id: str, uploads: list[tuple[str, bytes]]) -> None:
    batch = BATCHES[batch_id]
    batch.status = "processing"
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)
    searches: dict[str, asyncio.Task[tuple[list[Paper], dict[str, str]]]] = {}

    async def process_item(index: int, filename: str, data: bytes) -> None:
        item = batch.items[index]
        async with semaphore:
            item.status = "processing"
            try:
                extracted = await asyncio.to_thread(extract_pdf_data, data, filename)
                item.extracted = {key: value for key, value in extracted.items() if key != "query"}
                item.query = extracted["query"]
                cache_key = clean_doi(item.query) or normalize_title(item.query)
                if cache_key not in searches:
                    searches[cache_key] = asyncio.create_task(perform_search(item.query))
                item.results, item.source_status = await searches[cache_key]
                item.status = "completed"
                batch.completed += 1
            except HTTPException as exc:
                item.status = "failed"
                item.error = str(exc.detail)
                batch.failed += 1
            except Exception:
                item.status = "failed"
                item.error = "处理 PDF 时发生内部错误"
                batch.failed += 1

    await asyncio.gather(*(process_item(index, filename, data) for index, (filename, data) in enumerate(uploads)))
    batch.status = "completed"


@app.post("/api/pdf-batches", response_model=BatchStatus, status_code=202)
async def create_pdf_batch(files: list[UploadFile] = File(...)) -> BatchStatus:
    if not 1 <= len(files) <= MAX_BATCH_FILES:
        raise HTTPException(400, f"每批必须上传 1 到 {MAX_BATCH_FILES} 个 PDF")

    uploads: list[tuple[str, bytes]] = []
    total_size = 0
    for file in files:
        data = await file.read(MAX_PDF_SIZE + 1)
        if len(data) > MAX_PDF_SIZE:
            raise HTTPException(413, f"{file.filename or 'PDF'} 超过 15 MB")
        total_size += len(data)
        if total_size > MAX_BATCH_SIZE:
            raise HTTPException(413, "整批 PDF 不能超过 250 MB")
        uploads.append((file.filename or "unnamed.pdf", data))

    batch_id = uuid.uuid4().hex[:12]
    batch = BatchStatus(batch_id=batch_id, total=len(uploads), items=[BatchItem(filename=filename) for filename, _ in uploads])
    BATCHES[batch_id] = batch
    task = asyncio.create_task(process_pdf_batch(batch_id, uploads))
    RUNNING_BATCHES.add(task)
    task.add_done_callback(RUNNING_BATCHES.discard)
    return batch


@app.get("/api/pdf-batches/{batch_id}", response_model=BatchStatus)
async def get_pdf_batch(batch_id: str) -> BatchStatus:
    batch = BATCHES.get(batch_id)
    if batch is None:
        raise HTTPException(404, "批量任务不存在")
    return batch


@app.post("/api/format")
async def format_citations(request: FormatRequest) -> dict[str, Any]:
    if request.format.lower() not in FORMATS:
        raise HTTPException(400, "不支持的引用格式")
    formatted = format_items([item.model_dump() for item in request.items], request.format)
    return {"format": request.format.lower(), "citations": formatted, "text": "\n\n".join(formatted)}


@app.post("/api/export")
async def export_citations(request: FormatRequest) -> Response:
    if request.format.lower() not in FORMATS:
        raise HTTPException(400, "不支持的引用格式")
    style = request.format.lower()
    separator = "\n\n"
    content = separator.join(format_items([item.model_dump() for item in request.items], style)) + "\n"
    extension = "bib" if style == "bibtex" else "ris" if style == "ris" else "txt"
    media_type = "application/x-bibtex" if extension == "bib" else "application/x-research-info-systems" if extension == "ris" else "text/plain"
    return Response(content=content, media_type=f"{media_type}; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="paper-citations.{extension}"'})


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
