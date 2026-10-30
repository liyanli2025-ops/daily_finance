"""Freeze the edited macro report for one optional speech call; rehearse with mocks."""
import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
import zipfile


def digest(raw):return hashlib.sha256(raw).hexdigest()


def build(output,result_log,trial_id='macro-spoken-20261029-v1'):
    if trial_id not in ('macro-spoken-20261029-v1','macro-spoken-listener-20261030-v2'):
        raise ValueError('Unknown reviewed speech trial')
    repo=Path(__file__).resolve().parents[1];backend=repo/'backend'
    sys.path.insert(0,str(backend))
    from app.services.editorial_policy import spoken_prompts
    from app import programme_acceptance as runner
    body=(repo/'docs/macro_transfer_edited_report_20261029.md').read_bytes().replace(b'\r\n',b'\n')
    report=SimpleNamespace(content=body.decode('utf-8'),report_date=date(2026,10,29))
    system,user=spoken_prompts(report,report.report_date,'早报')
    messages=[dict(role='system',content=system),dict(role='user',content=user)]
    encoded=json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode()
    if len(encoded.decode())>12000:raise RuntimeError('Preview input too large')
    sources={name:digest((backend/'app/services'/name).read_bytes().replace(b'\r\n',b'\n')) for name in ('editorial_policy.py','spoken_programme.py','spoken_editing.py','podcast_generator.py')}
    packet=dict(owner=trial_id,report=report.content,report_sha256=digest(body),
        messages=messages,input_sha256=digest(encoded),input_characters=len(encoded.decode()),source_sha256=sources,
        max_output_tokens=4000,max_http_requests=1,retries=0)
    raw=json.dumps(packet,ensure_ascii=False,indent=2).encode()
    source=(repo/'tools/run_macro_spoken_once.py').read_text(encoding='utf-8').replace('BUILD_PACKET_SHA',digest(raw)).replace('BUILD_RUNNER_SHA',digest((backend/'app/programme_acceptance.py').read_bytes().replace(b'\r\n',b'\n')))
    source=source.replace("TRIAL='macro-spoken-20261029-v1'","TRIAL="+repr(trial_id))
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output exists')
    output.mkdir(parents=True)
    (output/'spoken.input.json').write_bytes(raw);(output/'edited-report.md').write_bytes(body)
    (output/'edited-metadata.json').write_bytes((repo/'docs/macro_transfer_edited_metadata_20261029.json').read_bytes())
    path=output/'run_macro_spoken_once.py';path.write_text(source,encoding='utf-8')
    spec=importlib.util.spec_from_file_location('macro_spoken_trial',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    text=Path(result_log).read_text(encoding='utf-8')
    original=text.split('=== 未审查报告，仅供人工验收 ===',1)[1].split('ubuntu@VM-0-6-ubuntu:',1)[0].strip()
    if digest(original.encode())!=module.ORIGIN_RESPONSE:raise RuntimeError('Wrong completed response')
    with tempfile.TemporaryDirectory(prefix='macro-spoken-rehearsal-') as folder:
        test=Path(folder)/'backend'
        (test/'data/diagnostics/staged-real-report').mkdir(parents=True);(test/'data/.automation-paused').touch()
        (test/'app/services').mkdir(parents=True)
        (test/'app/programme_acceptance.py').write_bytes((backend/'app/programme_acceptance.py').read_bytes())
        for name in sources:(test/'app/services'/name).write_bytes((backend/'app/services'/name).read_bytes())
        origin=test/'data/diagnostics/staged-real-report'/(module.ORIGIN+'.json')
        origin.write_text(json.dumps(dict(status='completed_for_human_review',input_sha256=module.ORIGIN_INPUT,response=original)),encoding='utf-8')
        assert module.load(test,output)==packet
        assert module.preview(packet)['http_requests_performed']==0
        assert not (test/'data/diagnostics/staged-programme').exists()
        origin.write_text('{}')
        try:module.load(test,output)
        except RuntimeError:pass
        else:raise AssertionError('Origin rejection missing')
        @dataclass
        class Route:
            provider:str='ofox_anthropic'
            model:str='anthropic/claude-sonnet-5.5'
            base_url:str='https://api.ofox.io'
            effort:str='high'
        quote='它们值得提高风险观察的优先级，但还不足以证明科技股将继续下跌。'
        reply=json.dumps(dict(programme=dict(mainline='风险消息与短线倾向',choices=[dict(topic='科技反弹',editorial_reason='风险与趋势有区别',report_quotes=[quote])],omitted=[]),script=quote),ensure_ascii=False)
        gateway=Mock();gateway.resolve_route.return_value=Route();gateway.request_for.return_value=('https://api.ofox.io/v1/messages',{},dict())
        gateway.completed_text.return_value=reply
        response=Mock(status_code=200,is_error=False);response.json.return_value=dict(stop_reason='end_turn',content=[dict(type='text',text=reply)])
        client=Mock();client.post.return_value=response;factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
        with patch.multiple(runner,TRIAL=module.TRIAL,REPORT_SHA=module.REPORT_SHA,MAX_TOKENS=4000,preview=module.preview):
            state=runner.execute(test,packet,packet['input_sha256'],gateway,factory,Mock(return_value={'mode':'mock_only'}))
            assert json.loads(state.read_text(encoding='utf-8'))['status']=='completed_for_human_review'
            runner.execute(test,packet,packet['input_sha256'],gateway,factory,Mock())
        client.post.assert_called_once();assert gateway.request_for.call_args.args[0].effort=='none'
    (output/'README.txt').write_text('默认只免费预览。人工修订历史底稿，仅验收口播编排与表达，不证明自主分析通过。\n--run与输入指纹才授权一次请求，零重试，无自动审查/TTS/发布/恢复调度。局部低推理不改变生产配置。\n保留永久标记，不重跑旧试验。此次最多4000输出token；字符不是token，实际费用以服务商账单为准。\n',encoding='utf-8')
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for file in output.iterdir():archive.write(file,output.name+'/'+file.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=digest(output.with_suffix('.zip').read_bytes()),input_sha256=packet['input_sha256'],input_characters=packet['input_characters'],real_model_requests=0,rehearsal='origin_binding_free_preview_one_mock_call_duplicate_refused')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--result-log',type=Path,required=True)
    parser.add_argument('--trial-id',default='macro-spoken-20261029-v1',choices=('macro-spoken-20261029-v1','macro-spoken-listener-20261030-v2'))
    args=parser.parse_args();print(json.dumps(build(args.output,args.result_log,args.trial_id),ensure_ascii=False,indent=2))
