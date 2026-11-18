"""Editorial focus for fresh editions, independent of source admissibility."""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from .time_context import CHINA_TIME


def hours(now):
    return 72 if now.weekday() in {5, 6, 0} else 24


def new_window(now):
    return dict(start=(now - timedelta(hours=hours(now))).isoformat(), cutoff=now.isoformat(),
                timezone='Asia/Shanghai')


def publication_hint(raw, window):
    """Conservatively label publication hints, never the time of the event."""
    if not isinstance(raw, str) or not raw.strip():
        return 'unknown'
    raw = raw.strip()
    try:
        try:
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            stamp = parsedate_to_datetime(raw)
        start = datetime.fromisoformat(window['start']).date()
        cutoff = datetime.fromisoformat(window['cutoff']).date()
        # Provider hints may mean publication, date-only or a local time in
        # an unspecified zone. Never order two developments from them.
        day = stamp.astimezone(CHINA_TIME).date() if stamp.tzinfo else stamp.date()
    except (ValueError, TypeError, OverflowError):
        return 'unknown'
    if day < start:
        return 'before_window'
    if day > cutoff:
        return 'after_cutoff_day'
    return 'in_window_day'


def packet(state, stage):
    window = state.get('news_focus')
    if not window:
        return {}
    view = dict(window)
    if stage in {'agenda', 'assessment', 'patch_assessment'}:
        groups = {}
        for cid, row in state.get('candidates', {}).items():
            tag = 'financial_background' if row.get('baseline_document') else publication_hint(
                row.get('published_hint'), window)
            groups.setdefault(tag, []).append(cid)
        if groups:
            view['publication_hints'] = groups
    return dict(news_focus=view)


def requirements(stage):
    common = ('\nnews_focus是本期新增事实或变化的重点时窗，交易另外使用对应市场最近已完成交易时段。'
        'publication_hints只标报道日期，不能据此判断事情何时发生；较早资料可说明背景或已经排定的节点。'
        '旧事只有确认出现新结果、新动作、新数据、重要回应或修正才重新进入主线。'
        '最新报道复述旧事不算新变化；预定事项到日可提示，结果须有已发布依据。')
    if stage == 'agenda':
        return common + ('\n交叉看发布者清单、中英文开放检索、市场、产业和公司定向检索，找本期影响大的新增变化。'
            'original_publisher标注原发布清单入口，仍未读正文；同一事实优先读能回答问题的原发布或现场报道。'
            '每个major只问一个可核查的新变化，标题与reason写清谁在何时做了什么、目前状态和影响路径；同一报道可以为多个变化提供线索。'
            '重要且疑似有新变化但证据未齐仍须保留，明确要核对什么。背景或仅待发生的事项列context或排除。'
            '一篇综述能发现多个线索；有专门报道或原披露候选优先选它验证具体事件。')
    if stage in {'assessment', 'patch_assessment'}:
        return common + ('\n逐项从正文核具体新增事实、时点和状态，检查综述正文有没有候选标题未写出的重要新变化。'
            '旧出处提到本期计划节点时，分开检查原安排、已发生进展和正式结果，不能用背景替后续。'
            '需要补查时优先核能改变听众判断、且截止前应已有进展的来源；先沿现有线索找原发布者。'
            'additional_searches的查询须指向缺失的具体事实，带主体、动作或文件名，避免重复搜索整类新闻。')
    return common + ('\n主线优先讲经核实的本期高影响变化，再交代必要背景和下一个观察节点。'
        '同一主题的旧事实、最新动作和下一步须能在文字与口播中分别听出来。')
