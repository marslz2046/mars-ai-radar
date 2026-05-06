# Mars AI Radar

一个面向个人阅读的 AI 信息雷达。它从公开来源抓取内容，生成静态
`data/news.json` 和 `data/source-status.json`，前端页面直接读取这些文件。

## 当前来源

- 极客公园 AI 新浪潮观察：已接入公开栏目页
- 小互 AI 日报：已接入公开日报页和最新一期精选
- WaytoAGI：已接入可访问的知识库精选页，并输出来源状态
- AI产品黄叔：暂停，等待稳定公开 feed
- 数字生命卡兹克：暂停，等待稳定公开 feed 或 GitHub 子源

## 本地运行

```bash
python scripts/update_news.py
python -m http.server 8787
```

打开：

```text
http://127.0.0.1:8787
```

## 发布

这个项目可以直接部署到 GitHub Pages。建议设置：

- Source: Deploy from a branch
- Branch: `main`
- Folder: `/ (root)`

GitHub Actions 会每天运行 `scripts/update_news.py` 并提交新的 `data/*.json`。

## 安全边界

- 不提交 API key、cookie、token、邮箱内容或私有 OPML。
- 不抓需要登录的微信公众号、X 私有时间线或私有知识库。
- 来源失败会写入 `data/source-status.json`，不会静默伪造内容。
