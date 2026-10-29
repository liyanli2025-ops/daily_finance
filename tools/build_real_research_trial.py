"""Freeze one new report-writing trial from locally reviewed real historical evidence."""
import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock
import zipfile

TRIAL='real-research-report-20261029-v1'


def build(review,research_archive,output):
    repo=Path(__file__).resolve().parents[1]
    data=json.loads(Path(review).read_text(encoding='utf-8'))
    if data.get('model_requests')!=0 or data.get('confirmed_sources')!=0:raise RuntimeError('Expected never-sent local review')
    with zipfile.ZipFile(research_archive) as archive:research=json.loads(archive.read('research-review.json'))
    rows=[dict(market=c['key'].split(':')[0],code=c['key'].split(':')[1],name=c['name']) for c in research['contexts']]
    messages=[dict(role='user',content=data['single_report_prompt'])]
    characters=len(json.dumps(messages,ensure_ascii=False,separators=(',',':')))
    if not 0<characters<=100000:raise RuntimeError('Fixed input exceeds character guard')
    packet=dict(owner='finance-staged-report-input-v1',messages=messages,watchlist=rows,
        snapshot_collected_at=data['news_snapshot'],research_exported_at=data['research_export'],
        input_characters=characters,max_output_tokens=8000,max_http_requests=1,retries=0,
        allowed_citation_ids=data['prepared_citation_ids'],source_revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip(),
        news_candidates=data['news_candidates'],selected_news=data['selected_news'],research_views=data['research_views'],
        research_source_documents=data['research_source_documents'],
        limitation='Real historical evidence, current initial fragments, one report only. No retrieval tools, live quote refresh, independent calendar or EventObservations history. Not a live broadcast, professional-quality verdict or full-pipeline acceptance.')
    encoded=json.dumps(packet,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    sha=hashlib.sha256(encoded).hexdigest()
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output exists')
    output.mkdir(parents=True);(output/'real-report.input.json').write_bytes(encoded)
    # Keep the old completed trial untouched. This new immutable copy uses the
    # same reviewed one-POST routine, with its own stable marker and input SHA.
    source=(repo/'tools/run_frozen_report_once.py').read_text(encoding='utf-8')
    source=source.replace("INPUT_SHA='0bf1cb2e8646ca392e318385e973ff0987a1085a90733b2f941c2fab240bfeb2'",f"INPUT_SHA='{sha}'\nTRIAL_ID='{TRIAL}'")
    source=source.replace("path=Path(backend)/'data/diagnostics/staged-report'/(INPUT_SHA+'.input.json')", "path=Path(__file__).with_name('real-report.input.json')")
    source=source.replace("folder=backend/'data/diagnostics/staged-report'", "folder=backend/'data/diagnostics/staged-real-report'\n    folder.mkdir(parents=True,exist_ok=True,mode=0o700)")
    source=source.replace("marker=folder/(INPUT_SHA+'.report.started')", "marker=folder/(TRIAL_ID+'.started')").replace("state=folder/(INPUT_SHA+'.report.json')", "state=folder/(TRIAL_ID+'.json')")
    start=source.index('def preview(packet):');end=source.index('\ndef execute(',start)
    preview="""def preview(packet):
    return dict(mode='free_preview',trial=TRIAL_ID,input_sha256=INPUT_SHA,
        snapshot_collected_at=packet['snapshot_collected_at'],research_exported_at=packet['research_exported_at'],
        input_characters=packet['input_characters'],model=MODEL,max_output_tokens=MAX_TOKENS,
        max_http_requests=1,retries=0,http_requests_performed=0,watchlist=packet['watchlist'],
        selected_news=packet['selected_news'],research_views=packet['research_views'],research_source_documents=packet['research_source_documents'],
        limitation='新历史资料报告验收，不再使用人工修正版报告；默认免费预览，--run才收费一次。无自动审查/修稿/口播/TTS/发布，不恢复调度。未接补查工具，不验收实时采集或完整生产流程。字符不是token，实际账单以服务商为准。')

"""
    source=source[:start]+preview+source[end:]
    source=source.replace('import argparse\n','import argparse\nimport re\n',1)
    source=source.replace('    save(state,data)\n    started=time.monotonic()',"    save(folder/(TRIAL_ID+'.input.json'),packet)\n    save(state,data)\n    started=time.monotonic()",1)
    source=source.replace("        data['status']='completed_for_human_review'", "        cited=set(re.findall(r'\\[N:([^\\]\\s]+)\\]',data['response']))\n        data['citation_check']=dict(unprovided_ids=sorted(cited-set(packet['allowed_citation_ids'])),limitation='ID存在不代表支持具体主张，仍待人工核验')\n        data['status']='completed_for_human_review'")
    # The regexp is checked in the simulated response rehearsal below.
    path=output/'run_real_report_once.py';path.write_text(source,encoding='utf-8')
    spec=importlib.util.spec_from_file_location('real_report_trial',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.load('/unused')==packet
    with tempfile.TemporaryDirectory(prefix='finance-report-trial-') as temporary:
        backend=Path(temporary);(backend/'data').mkdir();(backend/'data/.automation-paused').touch()
        @dataclass
        class Route:
            provider:str='ofox_anthropic'
            model:str='anthropic/claude-sonnet-5.5'
            base_url:str='https://api.ofox.io'
            effort:str='high'
        gateway=Mock();gateway.resolve_route.return_value=Route();gateway.request_for.return_value=('https://api.ofox.io/v1/messages',{},dict())
        response=Mock(status_code=200,is_error=False);response.json.return_value=dict(stop_reason='end_turn',content=[dict(type='text',text='报告[N:unprovided-test]')])
        gateway.completed_text.return_value='报告[N:unprovided-test]'
        client=Mock();factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False);client.post.return_value=response
        usage=Mock(return_value={'mode':'simulated_not_real_usage'})
        state=module.execute(backend,packet,gateway,factory,usage,Mock())
        result=json.loads(state.read_text(encoding='utf-8'))
        assert result['status']=='completed_for_human_review'
        assert result['citation_check']['unprovided_ids']==['unprovided-test']
        assert (state.parent/(TRIAL+'.input.json')).is_file()
        module.execute(backend,packet,gateway,factory,usage,Mock());client.post.assert_called_once()
    (output/'README.txt').write_text('默认只免费预览；--run只一次完整报告写作。无需安装生产补丁，不改服务或.env、数据库及暂停。\n输入是用户已导出的历史新闻/研究/技术片段，不是人工修正报告；不提供检索工具、不刷新行情，不自动审查/修稿/口播/语音/发布。\n结果与永久开始标记在backend/data/diagnostics/staged-real-report/real-research-report-20261029-v1.*；不删除标记重扣费。\n完整输入与原回复保留，默认没有模型请求；生成成功不代表专业性、准确率或可发布。\n',encoding='utf-8')
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for file in output.iterdir():archive.write(file,output.name+'/'+file.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),input_sha256=sha,input_characters=characters,max_http_requests=1,real_http_requests=0,rehearsal='free_load_simulated_one_POST_citation_warning_stable_marker_passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True);parser.add_argument('--research-archive',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.review,args.research_archive,args.output),ensure_ascii=False,indent=2))
