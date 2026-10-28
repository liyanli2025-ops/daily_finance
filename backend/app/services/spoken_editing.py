"""Conservative speech formatting and local reading-load diagnostics. No models."""
from collections import Counter
import json
import re

TTS_TEXT_VERSION='2026-10-28-exact-spoken-v1'


def tts_text(text):
    """Canonical text, prepared BEFORE review, never silently changed afterwards."""
    text=re.sub(r'[\u200b-\u200f\ufeff\u00ad]','',text)
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]','',text)
    # Do this before percent conversion changes the numeric right-hand side.
    text=re.sub(r'(?<=[\d%％])[—–](?=[+\-−]?\d)','至',text)
    text=clean(text)
    # Preserve the comparison that defines a forecast's trigger or invalidation.
    replacements={'≈':'约等于','≠':'不等于','≤':'小于或等于','≥':'大于或等于',
        '±':'正负','×':'乘以','÷':'除以','∞':'无穷',
        '→':'向右','←':'向左','↑':'向上','↓':'向下',
        '↔':'双向','↕':'上下','⇒':'向右','⇐':'向左','⇑':'向上','⇓':'向下','⇔':'双向'}
    for symbol,spoken in replacements.items():text=text.replace(symbol,spoken)
    # Numeric ranges differ from a rhetorical dash. Leave ISO dates and minus signs alone.
    text=text.replace('…','...').replace('—','，').replace('–','，').replace('·','，')
    text=re.sub(r'[ \t]+',' ',text)
    text=re.sub(r'(?m)^\s+$','',text)
    return text.strip()


def tts_segments(text):
    """Only split the reviewed canonical script; no second semantic cleanup."""
    if tts_text(text)!=text:
        raise RuntimeError('送入语音引擎的文本与核验规范不一致，停止合成；保留原稿供检查')
    segments=[part.strip() for part in text.split('[SECTION_BREAK]') if part.strip()]
    if not segments:raise RuntimeError('口播正文为空，停止合成')
    return segments


def report_body(text):
    """Remove only the terminal source catalogue produced by source_notes()."""
    matches=list(re.finditer(r'(?m)^#{1,6}\s+本期引用来源\s*$',text))
    if not matches:return text
    match=matches[-1]
    tail=[line.strip() for line in text[match.end():].splitlines() if line.strip()]
    if tail and all(line=='以下为采集来源，来源存在不等于内容已被独立证实。'
                    or re.match(r'^- \[N:[^\]\s]+\] ',line) for line in tail):
        return text[:match.start()].rstrip()
    return text


def stage_only(value):
    # Do not treat a bare “背景/过渡/语气” as a stage direction.
    value=value.casefold().strip()
    if value in {'音乐','音效','music','sound'}:return False
    if not re.search(r'音乐|音效|停顿|深呼吸|语速|语气|music|sound|pause|breath|bgm|fade|transition',value):return False
    tokens=('背景音乐','片头音乐','片尾音乐','音乐过渡','轻柔音乐','转场音效','音效',
            '音乐','渐弱','渐强','淡入','淡出','停顿','深呼吸','语速稍慢','语速放慢',
            '语速加快','语气轻松','语气严肃','轻声','播放','响起','秒',
            'background music','music','sound effect','sound','fade out','fade in','fades','fade','pause','breath','bgm','transition')
    pattern='|'.join(re.escape(word) for word in sorted(tokens,key=len,reverse=True))
    if not re.search(pattern,value):return False
    rest=re.sub(pattern,'',value)
    rest=re.sub(r'[\s，,。.;；:：!！、\-\d零一二三四五六七八九十两]+','',rest)
    return not rest


def _tables(text):
    lines=text.splitlines();result=[];index=0
    cells=lambda line:[value.strip() for value in line.strip().strip('|').split('|')]
    def separator(line):
        values=cells(line)
        return len(values)>1 and all(re.fullmatch(r':?-{2,}:?',value) for value in values)
    while index<len(lines):
        if index+1<len(lines) and '|' in lines[index] and separator(lines[index+1]):
            headers=cells(lines[index]);index+=2
            while index<len(lines) and '|' in lines[index]:
                values=cells(lines[index])
                if len(values)!=len(headers):break
                result.append('，'.join((header+'：' if header else '')+value for header,value in zip(headers,values))+'。')
                index+=1
            continue
        result.append(lines[index]);index+=1
    return '\n'.join(result)


def clean(text):
    text=report_body(text)
    # Strip a known report metadata block, but preserve unfamiliar fenced text.
    def fence(match):
        content=match.group(2)
        if match.group(1).lower()=='json':
            try:
                value=json.loads(content)
                if isinstance(value,dict) and {'title','summary','core_opinions','market_analysis'}<=set(value):return ''
            except ValueError:pass
        return content
    text=re.sub(r'```([a-zA-Z0-9_-]*)\s*\n([\s\S]*?)```',fence,text)
    def bracket(match):
        if re.search(r'语气|语速',match.group(1)):
            start=match.string.rfind('\n',0,match.start())+1
            end=match.string.find('\n',match.end())
            if end<0:end=len(match.string)
            if match.string[start:match.start()].strip() or match.string[match.end():end].strip():return match.group(0)
        return '' if stage_only(match.group(1)) else match.group(0)
    for pattern in (r'（([^（）]*)）',r'\(([^()]*)\)',r'\[([^\[\]]*)\]'):
        text=re.sub(pattern,bracket,text)
    text=re.sub(r'\*\*([^*\n]+)\*\*',lambda m:'' if stage_only(m.group(1)) else m.group(1),text)
    text=re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)',lambda m:'' if stage_only(m.group(1)) else m.group(1),text)
    text=re.sub(r'!?(\[([^\]]+)\])\((https?://[^\s)]+)\)',lambda m:m.group(2),text)
    text=re.sub(r'\[N:[^\]\s]+\]|\[(?:新闻|来源|参考)\d*\]','',text)
    # ASCII URL characters stop before adjacent Chinese facts/conditions.
    text=re.sub(r"https?://[A-Za-z0-9:/?#@!$&'()*+,;=%._~\-]+",'',text)
    text=_tables(text)
    text=re.sub(r'(?m)^#{1,6}\s+','',text)
    text=re.sub(r'(?m)^\s*(?:[-*]\s+|[1-9]\d?\.\s+)','',text)
    text=re.sub(r'(?m)^\s*注\d*[：:]\s*','',text)
    text=re.sub(r'`([^`]+)`',r'\1',text)
    text=re.sub(r'[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]','',text)
    def percent(match):
        sign={'-':'负','−':'负','+':'正','':''}[match.group(1)]
        return sign+'百分之'+match.group(2)
    text=re.sub(r'([+\-−]?)(\d+(?:\.\d+)?)\s*[%％]',percent,text)
    text=re.sub(r'\n{3,}','\n\n',text)
    return text.strip()


def audit(text):
    """Advisory surface checks, never a factual, investing or listening score."""
    visible=text.replace('[SECTION_BREAK]','')
    sentences=[part.strip() for part in re.split(r'[。！？!?\n]+',visible) if part.strip()]
    numbers=lambda value:re.findall(r'[+\-−]?\d+(?:\.\d+)?',value)
    long=[dict(characters=len(line),excerpt=line[:140]) for line in sentences if len(line)>90]
    dense=[dict(number_strings=len(numbers(line)),excerpt=line[:140]) for line in sentences if len(numbers(line))>=5]
    repeated=[dict(sentence=line[:140],count=count) for line,count in Counter(sentences).items() if len(line)>=12 and count>1]
    count=len(re.sub(r'\s+','',visible))
    return dict(characters=count,number_strings=len(numbers(visible)),
        long_sentences=long[:8],number_dense_sentences=dense[:8],repeated_sentences=repeated[:8],
        rough_minutes_range=[round(count/300,1),round(count/220,1)],
        limitation='仅表面阅读负荷提示，阈值非验证标准；时长按每分钟220—300字符粗估，未合成音频，不证明事实、推理或听感合格')
