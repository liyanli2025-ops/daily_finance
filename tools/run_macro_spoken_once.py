"""Free frozen speech preview; explicit --run plus input SHA authorizes one POST."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

TRIAL='macro-spoken-20261029-v1'
ORIGIN='macro-transfer-20261029-v1'
ORIGIN_INPUT='5b07d7d8e82f3fd450e7e02ea8e417ef264bd84c7e8e6377131b254a70f7d188'
ORIGIN_RESPONSE='d8923ed1d0339e69833be7fa1babe5f85931a48896e02125dd1087a901090854'
REPORT_SHA='08490408c4a0f7038621c98c48d7a6876b2358b9d1b22fbd7e7f922fe59e6db4'
PACKET_SHA='BUILD_PACKET_SHA'
RUNNER_SHA='BUILD_RUNNER_SHA'
MAX_TOKENS=4000


def digest(raw):return hashlib.sha256(raw).hexdigest()


def load(backend,bundle):
    backend=Path(backend);bundle=Path(bundle)
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('必须保持维护暂停')
    raw=(bundle/'spoken.input.json').read_bytes()
    if digest(raw)!=PACKET_SHA:raise RuntimeError('固定输入文件指纹不匹配')
    packet=json.loads(raw)
    report=(bundle/'edited-report.md').read_bytes().replace(b'\r\n',b'\n')
    if digest(report)!=REPORT_SHA or packet['report']!=report.decode('utf-8'):raise RuntimeError('修订底稿指纹不匹配')
    origin=json.loads((backend/'data/diagnostics/staged-real-report'/(ORIGIN+'.json')).read_text(encoding='utf-8'))
    if origin.get('status')!='completed_for_human_review' or origin.get('input_sha256')!=ORIGIN_INPUT:
        raise RuntimeError('缺少本次已完成的分析记录；不自动重新生成')
    response=origin.get('response','').replace('\r\n','\n').strip()
    if digest(response.encode('utf-8'))!=ORIGIN_RESPONSE:raise RuntimeError('分析原稿与已编辑版本不匹配；停止，不收费')
    if digest((backend/'app/programme_acceptance.py').read_bytes().replace(b'\r\n',b'\n'))!=RUNNER_SHA:
        raise RuntimeError('运行器与已核对版本不同')
    for name,sha in packet['source_sha256'].items():
        if digest((backend/'app/services'/name).read_bytes().replace(b'\r\n',b'\n'))!=sha:
            raise RuntimeError('正式口播源码与固定输入不同：'+name)
    return packet


def preview(packet):
    return dict(mode='free_preview',trial=TRIAL,input_sha256=packet['input_sha256'],
        report_sha256=REPORT_SHA,input_characters=packet['input_characters'],
        max_output_tokens=MAX_TOKENS,max_http_requests=1,retries=0,http_requests_performed=0,
        model='anthropic/claude-sonnet-5.5',local_reasoning_effort='none',
        origin=ORIGIN,manual_edit=True,
        limitation='历史单主题人工修正版，仅验收口播编排与表达，不代表自主分析通过或整期节目。默认免费；--run和输入指纹才收费一次。无自动审查、修稿、TTS、发布或恢复调度。字符不是token，实际扣费以账户为准。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--input-sha256')
    args=parser.parse_args()
    packet=load(args.backend,Path(__file__).parent)
    print(json.dumps(preview(packet),ensure_ascii=False,indent=2),flush=True)
    if not args.run:return
    if args.input_sha256!=packet['input_sha256']:parser.error('需要匹配免费预览的--input-sha256')
    sys.path.insert(0,str(args.backend.resolve()))
    from app import programme_acceptance as runner
    from app.services import model_gateway
    from app.services.model_usage import record_usage
    import httpx
    # Local standalone process only; no production source/config/marker edits.
    runner.TRIAL=TRIAL;runner.REPORT_SHA=REPORT_SHA;runner.MAX_TOKENS=MAX_TOKENS
    runner.preview=preview
    runner.execute(args.backend,packet,args.input_sha256,model_gateway,httpx.Client,record_usage)


if __name__=='__main__':main()
