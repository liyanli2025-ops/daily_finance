"""Narrowly identify a conditional six-month employee-plan reminder, not all notices."""
import re


def conditional_plan_reminder(title,body):
    title=re.sub(r'\s+','',title)
    if not re.search(r'员工持股计划.*存续期.*届满前(?:六|6)个月.*提示',title):return False
    text=re.sub(r'\s+','',body)
    if not re.search(r'决定是否(?:卖出|出售)股票|决定是否继续延长',text):return False
    # Conservatively keep any mention of a decided or executed action in the
    # active lane; this helper never asserts that no event exists on the web.
    if re.search(r'已(?:经|全部|累计|部分)*(?:卖出|出售|减持)|已(?:经)?决定|拟(?:出售|卖出|减持|延长|终止)|决定(?:继续)?延长|已终止|已延期|新增份额',text):
        return False
    return True
