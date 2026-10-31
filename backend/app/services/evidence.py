"""Deterministic provenance checks; these do not establish that a source is true."""
import re
from urllib.parse import urlsplit


def article_url(value):
    """A homepage is not traceable evidence for an individual news claim."""
    try:
        parsed = urlsplit(value or "")
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and (parsed.path not in {"", "/"} or bool(parsed.query)))
    except ValueError:
        return False


def validate_citations(content, news):
    by_id = {item.id: item for item in news}
    cited = set(re.findall(r"\[N:([^\]\s]+)\]", content))
    if not cited:
        raise RuntimeError("报告缺少新闻证据引用，停止发布")
    for identifier in cited:
        item = by_id.get(identifier)
        if item is None:
            raise RuntimeError(f"报告引用了不存在的新闻证据：[N:{identifier}]")
        if not article_url(item.source_url):
            raise RuntimeError(f"报告引用的新闻缺少可追溯的原文链接：[N:{identifier}]")
    return [by_id[key] for key in sorted(cited)]


def publication_label(item):
    impact=getattr(item,'market_impact','') or ''
    if '；精度：day；' in impact and '原始来源时点：' in impact:
        raw=impact.split('原始来源时点：',1)[1].split('；精度：',1)[0]
        return raw+'（日精度；内部日期区间起点不是实际发布时分）'
    if '；精度：minute；' in impact and '原始来源时点：' in impact:
        return impact.split('原始来源时点：',1)[1].split('；精度：',1)[0]+'（分钟精度）'
    return item.published_at.isoformat() if item.published_at else '来源未提供，不能推断'


def source_notes(news):
    lines = ["", "## 本期引用来源", "以下为采集来源，来源存在不等于内容已被独立证实。"]
    for item in news:
        title = item.title.replace("\n", " ")
        published = publication_label(item)
        lines.append(f"- [N:{item.id}] {title}｜{item.source}｜"
                     f"发布于 {published}｜{item.source_url}")
    return "\n".join(lines)
