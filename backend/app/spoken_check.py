"""Local formatting/reading-load inspection of saved material. No generation."""
import argparse
import json
from pathlib import Path

from .services.spoken_editing import clean,audit,report_body


def inspect(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('owner')=='finance-spoken-v1':
        text=data['script'];kind='saved_spoken_script'
    else:
        text=data['content'];kind='report_format_preview_not_a_generated_podcast'
    formatted=clean(text)
    return dict(case=Path(path).name,scope=kind,status='offline_format_audit_only',
        input_characters=len(text),report_body_characters=len(report_body(text)),
        formatted_characters=len(formatted),reading_load=audit(formatted),
        limitation='只检查已保存文本，不生成分析/播客、不核实事实、不调用模型或TTS；报告格式预览不是可发布口播稿')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(inspect(args.case),ensure_ascii=False,indent=2))
