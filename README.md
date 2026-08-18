# Paper Cite

本地论文检索与引用格式整理工具。

## 文档导航

- [接口文档](docs/API.md)：接口参数、响应结构、调用示例和错误码。
- [开发文档](docs/DEVELOPMENT.md)：环境搭建、项目结构、调试、测试及外网访问。
- 服务启动后还可以访问交互式接口文档：`http://127.0.0.1:8000/docs`。

## 1. 使用 uv 创建虚拟环境（推荐）

建议使用 Python 3.11 或更高版本。

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[test]"
```

创建完成后，终端提示符通常会显示 `(.venv)`。以后重新进入项目时，只需要激活已有环境：

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
source .venv/bin/activate
```

如果只运行应用、不运行测试，可以安装基础依赖：

```bash
uv pip install -e .
```

也可以不手动激活虚拟环境，直接通过 `uv run` 执行后续命令。

如果电脑还没有安装 `uv`，可以先使用普通虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

## 2. 启动开发服务

已激活 `.venv` 时运行：

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
uvicorn app:app --host 127.0.0.1 --port 8000
```

未激活 `.venv` 时，也可以运行：

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

启动后在浏览器打开：

```text
http://127.0.0.1:8000
```

健康检查地址：

```text
http://127.0.0.1:8000/api/health
```

服务依赖 Crossref、OpenAlex、Semantic Scholar、arXiv 和 PubMed 的网络接口。检索功能需要网络连接。Semantic Scholar 可选配置 `SEMANTIC_SCHOLAR_API_KEY` 以获得更稳定的请求配额。

## 3. 停止服务

在运行 `uvicorn` 的终端按：

```text
Ctrl+C
```

## 4. 运行测试

已激活 `.venv`：

```bash
cd /home/dhj/vsworkspace/vibecodding/paper-cite
pytest -q
```

或者直接使用 `uv run`：

```bash
uv run pytest -q
```

## 5. 退出虚拟环境

```bash
deactivate
```

## 6. 常用操作

- 输入 DOI、论文标题、arXiv ID 或 PubMed ID进行检索。
- 将候选论文加入右侧文献库后，可以编辑字段、排序和删除。
- 在底部选择 BibTeX、GB/T 7714、APA、IEEE 或 RIS 格式。
- 使用“复制预览”复制引用，或使用“导出文件”下载结果。
- 也可以拖入 PDF 文件，应用会尝试提取 DOI 或标题后自动检索。
