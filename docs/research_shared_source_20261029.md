# 服务器研究底稿改善与共享原文身份修正

## 用户已确认的服务器状态

分配修正5文件安装成功，备份/var/backups/finance-daily/20261029T063318949054Z；健康、数据库连接和维护暂停均通过。
同一批33份缓存，实际准备12条、3850原文字符，prompt7687/8000；之前为4条、603原文字符。12条包含公告、交流、研报、行业观察、经营简报/日历与财务背景，HTTP/模型请求0。此结果只确认分配改善，不确认分析或资料价值通过。

入选标题中，国家统计局“2026年9月份规模以上工业增加值增长5.5%”以同ID16e8d9d9e168e886ea4e0944关联宁德和华海。12条只有11个不同ID；不能称12份独立证据。也不能仅凭标题判员工持股提示/论坛研报无用，必须核对具体内容、日期和影响机制。

## 代码中确认的问题

primary_sources.government_article按公司业务families挑选原文段落；旧ResearchHub.material只按kind+URL+period生成ID。同一来源针对两个行业保留不同正文时会使用同ID，EpisodeWorkspace.add将以正文冲突停止；同正文的不同关联范围则可能被后一次覆盖。当前用户实际两份NBS节选是否相同尚未获取，不能说已在服务器触发此异常。

## 本地修正（未部署）

- 政府行业观察的阅读视图ID按原文组及存储正文生成，相同视图稳定，不随名单中是否出现另一个公司变化；不同段落可分别保留。
- source_id/原文组仍按kind+URL+period，多个视图仍是一份来源，不算独立交叉验证。
- 同正文视图合并关联范围，初始正文只提供一次，后续共享记录不重复计数；不同节选保留各自scope。不是按URL一刀切删除行业段落。
- 完整池和初选使用一致的视图规范；资料池合并同视图的scope_links，不覆盖原关联。未知ID冲突仍停止，不静默选择一个版本。
- 原缓存文件和所有旧报告、付费结果、输入及marker不重写；规范化仅在当前内存资料中进行。
- 免费检查增加不同原文组数量及source_id，使阅读视图与原文份数分开。

552项后端测试通过（20.361秒），新增5项覆盖旧同ID不同政府节选进入完整池、同段跨股票只读一次且保留两范围、视图ID稳定、未知冲突拒绝、缓存文件不改写。没有调用真实模型/TTS/新源API，不发新安装包，线上仍是已确认的分配修正版本。

## 下一步需要同一批真实缓存，而非继续夹具调参

此前用户提供的finance-material-review归档没有独立ResearchHub缓存。下一步免费导出33份公开研究底稿、实际初始输入和范围，供本地检查正文及回放上述修正，避免每改一处就让用户部署测试。导出不含.env、App数据库或请求头，也不自动采集；若缓存已过期则停止，不伪称全网无资料。

Ubuntu终端执行以下只读导出；/tmp目标若已存在会拒绝覆盖。执行后从腾讯云文件管理下载ZIP，提供到本对话：

```bash
cd /var/www/finance-daily/backend && sudo ./venv/bin/python - <<'PY'
import asyncio, json, os, zipfile
from pathlib import Path
from app.services.watchlist_repository import refresh_app_watchlist, watchlist_signature, assert_watchlist_current
from app.services.research_hub import ResearchHub
from app.services.time_context import china_now

async def main():
    service = await refresh_app_watchlist()
    stocks = service.get_all_stocks()
    signature = watchlist_signature(stocks)
    hub = ResearchHub()
    contexts = hub.load(stocks)
    if not any(c.get("materials") for c in contexts):
        raise RuntimeError("没有有效研究缓存；未自动采集或调用模型")
    prompt, evidence = hub.prompt(stocks, max_characters=8000)
    fields = ("id", "title", "source", "source_url", "kind", "scope", "body", "published_at", "collected_at", "period", "reading_status")
    profile_fields = ("key", "company", "industry", "business", "fields", "source", "source_url", "collected_at")
    rows = [{"key": c["key"], "name": c["name"], "collected_at": c.get("collected_at"),
             "profile": {k: c["profile"].get(k) for k in profile_fields} if c.get("profile") else None,
             "materials": [{k: m.get(k) for k in fields} for m in c.get("materials", [])]} for c in contexts]
    await assert_watchlist_current(signature)
    out = Path("/tmp/finance-research-review-20261029.zip")
    data = {"created_at": china_now().isoformat(), "contexts": rows,
            "initial_reading": hub.prompt_reading, "model_requests": 0,
            "limitation": "当前有效缓存及已准备输入，不代表模型读过或内容核验通过"}
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("research-review.json", json.dumps(data, ensure_ascii=False, indent=2, default=str))
        archive.writestr("initial-prompt.txt", prompt)
    print("导出文件：", out)
    print("缓存材料：", sum(len(c["materials"]) for c in rows), "；入选记录：", len(evidence))
    print("未采集、未调用模型、未生成音频；没有导出.env、数据库或请求头。")

asyncio.run(main())
PY
```

需要核对的优先问题：统计段落对两家公司的具体关联与来源重复；宁德交流/研报是否提供盈利承压的原因及反方；牧原提示性公告相对行业经营变化是否值得占位；华海论坛研报能否支持本期问题。财报仍只是参考，不围绕四股逐一凑新闻，不把官方资料或题目本身当深度分析。
