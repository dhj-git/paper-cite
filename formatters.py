import hashlib
import re
import unicodedata
from typing import Any

FORMATS = {"bibtex", "gbt7714", "apa", "ieee", "ris"}


def _authors(item: dict[str, Any]) -> list[str]:
    value = item.get("authors") or []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r";|\n", value) if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _is_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _person_parts(name: str) -> tuple[str, str]:
    if "," in name:
        family, given = (part.strip() for part in name.split(",", 1))
        return family, given
    parts = name.split()
    if len(parts) > 1 and not _is_chinese(name):
        return parts[-1], " ".join(parts[:-1])
    return name, ""


def _bib_escape(text: Any) -> str:
    value = str(text or "")
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def citation_key(item: dict[str, Any]) -> str:
    authors = _authors(item)
    family = _person_parts(authors[0])[0] if authors else "anon"
    ascii_family = unicodedata.normalize("NFKD", family).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]", "", ascii_family) or "anon"
    year = str(item.get("year") or "nd")
    identity = str(item.get("doi") or item.get("title") or "untitled").lower()
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:6]
    return f"{stem}{year}{suffix}"


def _kind(item: dict[str, Any]) -> str:
    value = str(item.get("type") or "article").lower()
    if "proceed" in value or "conference" in value:
        return "conference"
    if "preprint" in value or "posted" in value or "arxiv" in str(item.get("venue", "")).lower():
        return "preprint"
    return "article"


def format_bibtex(item: dict[str, Any]) -> str:
    kind = _kind(item)
    entry_type = "inproceedings" if kind == "conference" else "misc" if kind == "preprint" else "article"
    fields: list[tuple[str, Any]] = [
        ("author", " and ".join(_authors(item))), ("title", item.get("title")),
        ("year", item.get("year")),
    ]
    if kind == "conference":
        fields.append(("booktitle", item.get("venue")))
    elif kind == "article":
        fields.append(("journal", item.get("venue")))
    else:
        fields.append(("howpublished", item.get("venue") or "arXiv preprint"))
    fields.extend([
        ("volume", item.get("volume")), ("number", item.get("issue")),
        ("pages", item.get("pages")), ("publisher", item.get("publisher")),
        ("doi", item.get("doi")), ("url", item.get("url")),
    ])
    lines = [f"@{entry_type}{{{citation_key(item)},"]
    present = [(key, value) for key, value in fields if value not in (None, "", [])]
    lines.extend(f"  {key} = {{{_bib_escape(value)}}}{',' if index < len(present) - 1 else ''}" for index, (key, value) in enumerate(present))
    lines.append("}")
    return "\n".join(lines)


def _gb_authors(item: dict[str, Any]) -> str:
    authors = _authors(item)
    if not authors:
        return "佚名"
    chinese = _is_chinese("".join(authors))
    shown = authors[:3]
    if chinese:
        value = ", ".join(shown)
        return value + (", 等" if len(authors) > 3 else "")
    formatted = []
    for name in shown:
        family, given = _person_parts(name)
        initials = "".join(part[0].upper() for part in re.split(r"[\s-]+", given) if part)
        formatted.append(f"{family.upper()} {initials}".strip())
    return ", ".join(formatted) + (", et al." if len(authors) > 3 else "")


def format_gbt7714(item: dict[str, Any]) -> str:
    kind = _kind(item)
    marker = "C" if kind == "conference" else "J"
    venue = str(item.get("venue") or ("arXiv" if kind == "preprint" else ""))
    year = str(item.get("year") or "")
    details = year
    if item.get("volume"):
        details += f", {item['volume']}"
    if item.get("issue"):
        details += f"({item['issue']})"
    if item.get("pages"):
        details += f": {item['pages']}"
    result = f"{_gb_authors(item)}. {item.get('title') or 'Untitled'}[{marker}]."
    if venue:
        result += f" {venue},"
    if details:
        result += f" {details}."
    if item.get("doi"):
        result += f" DOI:{item['doi']}."
    elif item.get("url"):
        result += f" {item['url']}."
    return result


def _apa_author(name: str) -> str:
    family, given = _person_parts(name)
    if not given:
        return family
    initials = " ".join(f"{part[0].upper()}." for part in re.split(r"[\s-]+", given) if part)
    return f"{family}, {initials}"


def format_apa(item: dict[str, Any]) -> str:
    authors = _authors(item)
    author_text = ", ".join(_apa_author(name) for name in authors[:-1])
    if len(authors) > 1:
        author_text += (", " if len(authors) > 2 else "") + f"& {_apa_author(authors[-1])}"
    elif authors:
        author_text = _apa_author(authors[0])
    else:
        author_text = "Anonymous"
    result = f"{author_text} ({item.get('year') or 'n.d.'}). {item.get('title') or 'Untitled'}."
    if item.get("venue"):
        result += f" {item['venue']}"
        if item.get("volume"):
            result += f", {item['volume']}"
        if item.get("issue"):
            result += f"({item['issue']})"
        if item.get("pages"):
            result += f", {item['pages']}"
        result += "."
    if item.get("doi"):
        result += f" https://doi.org/{item['doi']}"
    elif item.get("url"):
        result += f" {item['url']}"
    return result


def format_ieee(item: dict[str, Any], index: int = 1) -> str:
    authors = _authors(item)
    author_text = ", ".join(authors[:6]) + (", et al." if len(authors) > 6 else "") if authors else "Anonymous"
    result = f'[{index}] {author_text}, “{item.get("title") or "Untitled"},”'
    if item.get("venue"):
        result += f" {item['venue']},"
    if item.get("volume"):
        result += f" vol. {item['volume']},"
    if item.get("issue"):
        result += f" no. {item['issue']},"
    if item.get("pages"):
        result += f" pp. {item['pages']},"
    if item.get("year"):
        result += f" {item['year']}."
    if item.get("doi"):
        result += f" doi: {item['doi']}."
    elif item.get("url"):
        result += f" [Online]. Available: {item['url']}"
    return result


def format_ris(item: dict[str, Any]) -> str:
    kind = _kind(item)
    ris_type = "CPAPER" if kind == "conference" else "RPRT" if kind == "preprint" else "JOUR"
    lines = [f"TY  - {ris_type}"]
    lines.extend(f"AU  - {author}" for author in _authors(item))
    mapping = [("TI", "title"), ("JO", "venue"), ("PY", "year"), ("VL", "volume"), ("IS", "issue"), ("PB", "publisher"), ("DO", "doi"), ("UR", "url")]
    for tag, key in mapping:
        if item.get(key) not in (None, ""):
            lines.append(f"{tag}  - {item[key]}")
    pages = str(item.get("pages") or "")
    if pages:
        parts = re.split(r"[-–—]", pages, maxsplit=1)
        lines.append(f"SP  - {parts[0].strip()}")
        if len(parts) > 1:
            lines.append(f"EP  - {parts[1].strip()}")
    lines.append("ER  -")
    return "\n".join(lines)


def format_items(items: list[dict[str, Any]], style: str) -> list[str]:
    style = style.lower()
    if style not in FORMATS:
        raise ValueError(f"Unsupported format: {style}")
    functions = {"bibtex": format_bibtex, "gbt7714": format_gbt7714, "apa": format_apa, "ris": format_ris}
    if style == "ieee":
        return [format_ieee(item, index) for index, item in enumerate(items, 1)]
    return [functions[style](item) for item in items]
