# Paper Cite 开发文档

## 技术栈

- Python 3.11+
- FastAPI：HTTP API 与静态文件服务
- httpx：并发请求外部论文数据源
- PyMuPDF：读取 PDF 元数据和首页文本
- 原生 HTML、CSS、JavaScript：浏览器界面
- pytest：自动化测试

## 项目结构

```text
paper-cite/
├── app.py              # API、数据模型、检索聚合及静态文件挂载
├── formatters.py       # BibTeX、GB/T 7714、APA、IEEE、RIS 格式化
├── static/
│   ├── index.html      # 页面结构
│   ├── app.js          # 前端状态与接口调用
│   └── styles.css      # 页面样式
├── tests/
│   └── test_app.py     # API 和格式化器测试
├── docs/
│   ├── API.md          # 接口文档
│   └── DEVELOPMENT.md  # 本文档
└── pyproject.toml      # 项目元数据与依赖
```

## 安装环境

推荐使用 `uv`：

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[test]"
```

也可以使用 Python 自带虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

## 启动开发服务

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

没有激活虚拟环境时：

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

常用地址：

- 应用首页：`http://127.0.0.1:8000`
- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- 健康检查：`http://127.0.0.1:8000/api/health`

FastAPI 最后将 `static/` 挂载在根路径，因此新增 API 路由时应继续放在 `app.mount("/", ...)` 之前。

## 运行流程

### 文献检索

1. 浏览器请求 `/api/search`。
2. 后端并发查询 Crossref、OpenAlex、Semantic Scholar、arXiv 和 PubMed。
3. 后端按 DOI 优先、规范化标题兜底的方式去重。
4. 合并数据来源和缺失字段，并按匹配度倒序返回。
5. 某个数据源失败时保留其他来源的结果，并在 `source_status` 中报告失败。

### PDF 检索

1. 检查 15 MB 大小限制和 PDF 文件头。
2. 读取 PDF 元数据及首页前 12,000 个字符。
3. 优先提取 DOI，否则使用元数据标题或首页首个合适的文本行。
4. 将提取结果交给普通检索流程。

### 引用生成

前端把文献库完整提交给 `/api/format`。格式化逻辑集中在 `formatters.py`，导出接口复用相同逻辑，避免预览和下载结果不一致。

## 外部依赖

检索功能依赖以下公开接口：

| 数据源 | 用途 |
| --- | --- |
| Crossref | DOI 和出版物元数据 |
| OpenAlex | 综合学术作品元数据 |
| Semantic Scholar | 计算机论文、开放 PDF 和出版信息补充 |
| arXiv | 预印本搜索及 arXiv ID 查询 |
| PubMed | 生物医学论文及 PMID 查询 |

后端为外部请求设置 12 秒总超时和 5 秒连接超时。开发时如果健康检查正常但搜索结果为空或部分失败，优先检查网络和 `source_status`。

Semantic Scholar 在没有 API Key 时也能使用公开接口，但限额较低。需要更稳定的请求配额时，申请 API Key 后在启动服务前设置：

```bash
export SEMANTIC_SCHOLAR_API_KEY="your-api-key"
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

应用只会将该值作为 Semantic Scholar 请求的 `x-api-key` 请求头发送。

## 测试

```bash
uv run pytest -q
```

当前测试覆盖健康检查、非法引用格式、非 PDF 上传，以及全部引用格式的基本输出。涉及外部接口的搜索测试应使用 mock，避免把测试稳定性绑定到网络服务。

新增功能时建议至少覆盖：

- 新接口的成功和失败响应
- 新字段的默认值与校验规则
- 新引用格式中的缺失字段、中文作者和英文作者
- PDF 大小、格式和无法提取内容的边界情况

## 临时开放到外网

本地服务启动后，可以另开终端运行 Cloudflare Quick Tunnel：

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

命令会输出一个临时的 `https://*.trycloudflare.com` 地址，不需要自有域名。访问期间必须保持本地程序、电脑网络和 `cloudflared` 都处于运行状态。

Quick Tunnel 适合演示和临时测试，不适合作为正式部署方案，原因包括地址会变化、依赖本地电脑在线，并且当前应用没有登录认证。不要用它公开包含敏感论文或内部数据的实例。

长期使用时，建议选择以下方式之一：

- 使用自有域名和命名 Cloudflare Tunnel，并通过 Cloudflare Access 增加身份验证。
- 将应用部署到云服务器或容器平台，再配置 HTTPS 和访问控制。

## 配置与安全注意事项

- `SEMANTIC_SCHOLAR_API_KEY` 是可选配置；当前仍没有用户登录机制。
- 应用数据只保存在浏览器页面状态中，刷新页面会清空文献库。
- PDF 会在单次请求内存中处理，不会主动写入磁盘。
- 对公网开放前应增加认证、请求频率限制、上传频率限制和日志策略。
- 若前后端分域部署，需要调整 CORS 白名单，不能继续只允许本机来源。
- 正式运行时不要启用 `--reload`。

## 常见问题

### 首页可以打开，但搜索失败

检查服务器是否能访问五个外部数据源，并查看页面显示的各数据源状态。健康检查只说明本地进程正常，不代表外部接口可用。

### 修改代码后没有生效

开发环境使用 `--reload`；若未启用，需要手动重启 Uvicorn。浏览器静态资源也可能需要强制刷新。

### Cloudflare 地址无法访问

先确认 `http://127.0.0.1:8000/api/health` 在本机可用，再检查 `cloudflared` 进程是否仍在运行。Quick Tunnel 地址会在重新启动后改变。
