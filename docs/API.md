# Paper Cite 接口文档

## 基本信息

- 本地基础地址：`http://127.0.0.1:8000`
- 数据格式：除 PDF 上传和文件下载外，均使用 JSON
- 字符编码：UTF-8
- 认证：当前版本没有身份认证
- OpenAPI：`/openapi.json`
- Swagger UI：`/docs`
- ReDoc：`/redoc`

搜索接口会访问 Crossref、OpenAlex、Semantic Scholar、arXiv 和 PubMed，因此服务端需要能够访问互联网。

## 数据模型

### Paper

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 否 | 服务端生成的 12 位文献标识 |
| `title` | string | 是 | 论文标题 |
| `authors` | string[] | 否 | 作者列表 |
| `year` | integer/null | 否 | 发表年份 |
| `venue` | string | 否 | 期刊、会议或预印本平台 |
| `volume` | string | 否 | 卷号 |
| `issue` | string | 否 | 期号 |
| `pages` | string | 否 | 页码范围 |
| `publisher` | string | 否 | 出版机构 |
| `type` | string | 否 | 文献类型，默认 `article` |
| `doi` | string | 否 | 规范化为小写的 DOI，不含 `https://doi.org/` |
| `url` | string | 否 | 论文正式页面 |
| `source_url` | string | 否 | 数据来源页面或接口地址 |
| `sources` | string[] | 否 | 数据来源，如 `Crossref`、`OpenAlex` |
| `confidence` | number | 否 | 查询匹配度，范围约为 0 到 1 |

提交格式化请求时，只有 `title` 是必填字段，其余字段均有默认值。

### SearchResponse

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string | 实际用于检索的内容 |
| `results` | Paper[] | 去重并按匹配度倒序排列的候选结果 |
| `source_status` | object | 各数据源的执行状态 |
| `extracted` | object/null | 仅 PDF 接口返回提取结果 |

## 健康检查

`GET /api/health`

```bash
curl http://127.0.0.1:8000/api/health
```

成功响应：

```json
{"status":"ok"}
```

## 检索论文

`GET /api/search?q={query}`

`q` 长度必须在 2 到 500 个字符之间，可以是标题、DOI、arXiv ID 或 PubMed ID。

```bash
curl --get http://127.0.0.1:8000/api/search \
  --data-urlencode "q=10.1038/s41586-020-2649-2"
```

响应示例：

```json
{
  "query": "10.1038/s41586-020-2649-2",
  "results": [
    {
      "id": "a1b2c3d4e5f6",
      "title": "示例论文标题",
      "authors": ["Example Author"],
      "year": 2020,
      "venue": "Example Journal",
      "volume": "1",
      "issue": "",
      "pages": "1-10",
      "publisher": "Example Publisher",
      "type": "journal-article",
      "doi": "10.1038/s41586-020-2649-2",
      "url": "https://doi.org/10.1038/s41586-020-2649-2",
      "source_url": "https://api.crossref.org/works/10.1038%2Fs41586-020-2649-2",
      "sources": ["Crossref", "OpenAlex", "Semantic Scholar"],
      "confidence": 1.0
    }
  ],
  "source_status": {
    "Crossref": "成功 (1)",
    "OpenAlex": "成功 (1)",
    "Semantic Scholar": "成功 (1)",
    "arXiv": "成功 (0)",
    "PubMed": "成功 (0)"
  },
  "extracted": null
}
```

单个外部数据源失败不会让整个请求失败，失败信息会出现在 `source_status` 中。

## 上传并解析 PDF

`POST /api/pdf`

- 请求类型：`multipart/form-data`
- 表单字段：`file`
- 大小限制：15 MB
- 文件内容必须以 PDF 文件头 `%PDF-` 开始

```bash
curl -X POST http://127.0.0.1:8000/api/pdf \
  -F "file=@./paper.pdf;type=application/pdf"
```

服务会优先从 PDF 首页或元数据中提取 DOI，否则尝试提取标题，然后调用与检索接口相同的数据源。响应结构为 `SearchResponse`，并额外包含：

```json
{
  "extracted": {
    "filename": "paper.pdf",
    "title": "Extracted title",
    "doi": "10.1234/example",
    "metadata": {
      "author": "Example Author",
      "subject": "",
      "keywords": ""
    }
  }
}
```

## 格式化引用

`POST /api/format`

支持的 `format`：`bibtex`、`gbt7714`、`apa`、`ieee`、`ris`。

```bash
curl -X POST http://127.0.0.1:8000/api/format \
  -H "Content-Type: application/json" \
  -d '{
    "format": "apa",
    "items": [{
      "title": "A Study & More",
      "authors": ["Jane Smith", "Wei Zhang"],
      "year": 2024,
      "venue": "Example Journal",
      "volume": "12",
      "issue": "3",
      "pages": "10-20",
      "doi": "10.1234/example"
    }]
  }'
```

成功响应：

```json
{
  "format": "apa",
  "citations": ["Smith, J. & Zhang, W. (2024). A Study & More. Example Journal, 12(3), 10-20. https://doi.org/10.1234/example"],
  "text": "Smith, J. & Zhang, W. (2024). A Study & More. Example Journal, 12(3), 10-20. https://doi.org/10.1234/example"
}
```

`citations` 保留逐条结果，`text` 使用两个换行符连接全部结果，适合直接预览或复制。

## 导出引用文件

`POST /api/export`

请求体与 `/api/format` 相同，响应为下载文件：

| 格式 | 文件扩展名 | Content-Type |
| --- | --- | --- |
| `bibtex` | `.bib` | `application/x-bibtex` |
| `ris` | `.ris` | `application/x-research-info-systems` |
| 其他格式 | `.txt` | `text/plain` |

```bash
curl -X POST http://127.0.0.1:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{"format":"bibtex","items":[{"title":"Example Paper","authors":["Jane Smith"],"year":2024}]}' \
  --output paper-citations.bib
```

## 错误响应

接口使用 FastAPI 标准错误结构：

```json
{"detail":"错误说明"}
```

| 状态码 | 常见原因 |
| --- | --- |
| `400` | PDF 无效、PDF 无页面、无法解析 PDF、引用格式不支持 |
| `413` | PDF 超过 15 MB |
| `422` | 参数校验失败，或无法从 PDF 提取 DOI/标题 |
| `500` | 未处理的服务端错误 |

## CORS 说明

当前仅允许来自 `localhost` 或 `127.0.0.1` 的浏览器跨域请求。项目自带前端与 API 由同一个 FastAPI 服务提供，因此正常访问首页时不受该限制。若以后把前端部署到其他域名，需要同步调整 `app.py` 中的 CORS 配置。
