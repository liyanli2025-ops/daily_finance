"""Task-specific model routing shared by reports and podcasts.

Explicit credentials only. No anonymous providers, model-name guessing, or
silent downgrade after a verification failure.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..config import settings

log = logging.getLogger(__name__)
TASKS = {"analysis", "review", "extraction", "podcast"}


def service_error(task, response):
    """Classify billing/auth errors without logging provider bodies or credentials."""
    try:
        data = response.json()
        error = data.get('error', {}) if isinstance(data, dict) else {}
        if isinstance(error, dict):
            text = ' '.join(str(error.get(field,'')) for field in ('type','code','message')).lower()
        else:
            text = str(error).lower()
    except (ValueError, TypeError):
        text = ''
    status = response.status_code
    if status == 402:
        detail = ('余额或额度不足（服务商返回说明）' if any(word in text for word in
                  ('insufficient','balance','credit','quota','余额','额度','欠费')) else
                  '支付或额度限制，服务商未提供可确认的具体原因')
    elif status in (401,403):
        detail = '凭据或模型访问权限未通过，不自动切换服务商'
    elif status == 410:
        detail = '所选模型或端点已停用，需核对服务商目录'
    else:
        detail = '服务商拒绝或未完成请求'
    return RuntimeError(f'{task}模型服务返回HTTP {status}：{detail}')


class IncompleteOutputError(RuntimeError):
    def __init__(self, reason, data):
        self.reason = reason if reason in {
            "max_tokens", "length", "refusal", "tool_use", "stop_sequence", "pause_turn"
        } else "unknown"
        usage = data.get("usage") or {}
        tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        count = tokens if type(tokens) is int else "unknown"
        super().__init__(f"模型输出未正常结束：reason={self.reason}, output_tokens={count}；禁止发布不完整结果")


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    base_url: str
    api_key: str
    effort: str


def resolve_route(task, config=None):
    config = config or settings
    if task not in TASKS:
        raise ValueError(f"Unknown model task: {task}")
    provider = getattr(config, f"{task}_provider") or config.ai_provider
    if provider == "auto":
        if config.openai_api_key:
            provider = "compatible"
        elif config.anthropic_api_key:
            provider = "anthropic"
        else:
            raise RuntimeError("未配置模型凭据；请配置主服务或阶段服务，不使用匿名免费服务")
    role_model = getattr(config, f"{task}_model")
    if provider == "backup":
        key, base = config.backup_ai_api_key, config.backup_ai_base_url
        model = role_model or config.backup_ai_model
    elif provider == "anthropic":
        key, base = config.anthropic_api_key, "https://api.anthropic.com/v1"
        model = role_model or config.ai_model
    elif provider == "compatible":
        key, base = config.openai_api_key, config.openai_base_url or "https://api.openai.com/v1"
        model = role_model or config.ai_model
    else:
        raise ValueError(f"Unsupported model provider: {provider}")
    if not key or not model or not base:
        raise RuntimeError(f"{task}阶段缺少密钥、地址或明确的模型名称")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ValueError("模型服务必须使用不含凭据或查询参数的HTTPS地址")
    # Ofox's current Claude catalog is exposed via Anthropic Messages. Keep the
    # existing Ofox credential without misrouting it to api.anthropic.com.
    if (provider == "compatible" and parsed.hostname in {"api.ofox.ai", "api.ofox.io"}
            and model.startswith("anthropic/")):
        provider = "ofox_anthropic"
        base = f"https://{parsed.hostname}/anthropic/v1"
    return Route(provider, model, base.rstrip("/"), key,
                 getattr(config, f"{task}_reasoning_effort"))


def request_for(route, messages, max_tokens):
    if route.provider in {"anthropic", "ofox_anthropic"}:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        body = {"model": route.model, "max_tokens": max_tokens,
                "messages": [m for m in messages if m["role"] != "system"]}
        # Sonnet 5.5 thinks by default and rejects thinking.type=disabled.
        # Honour the configured effort using its native protocol, rather than
        # silently leaving a small text budget to be consumed by thinking.
        if route.model.rsplit("/", 1)[-1] in {"claude-sonnet-5.5", "claude-sonnet-5-5"}:
            body["thinking"] = {"type": "between_tools" if route.effort == "none" else "adaptive"}
            body["output_config"] = {"effort": "low" if route.effort == "none" else route.effort}
        if system:
            body["system"] = system
        return route.base_url + "/messages", {
            "x-api-key": route.api_key, "anthropic-version": "2023-06-01"}, body
    body = {"model": route.model, "messages": messages, "max_tokens": max_tokens}
    host = urlsplit(route.base_url).hostname
    if host == "api.deepseek.com":
        enabled = route.effort != "none"
        body["thinking"] = {"type": "enabled" if enabled else "disabled"}
        if enabled:
            body["reasoning_effort"] = route.effort
    elif route.effort != "none":
        # Provider-specific request semantics must be configured explicitly.
        body["reasoning_effort"] = route.effort
    return route.base_url + "/chat/completions", {"Authorization": f"Bearer {route.api_key}"}, body


def completed_text(route, data):
    if route.provider in {"anthropic", "ofox_anthropic"}:
        if data.get("stop_reason") != "end_turn":
            raise IncompleteOutputError(data.get("stop_reason"), data)
        text = "\n".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")
    else:
        choices = data.get("choices") or []
        if not choices or choices[0].get("finish_reason") != "stop":
            raise IncompleteOutputError(choices[0].get("finish_reason") if choices else None, data)
        message = choices[0].get("message") or {}
        if message.get("refusal"):
            raise RuntimeError("模型拒绝生成，停止本次任务")
        text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("模型没有返回可用正文")
    return text.strip()


async def complete(task, messages, max_tokens=4000):
    from .model_usage import reserve_call, record_usage
    from .prompt_reading import validate_input
    request_characters=validate_input(messages)
    route = resolve_route(task)
    url, headers, body = request_for(route, messages, max_tokens)
    # Report only metadata, never prompts, keys, raw errors, or reasoning content.
    log.info("model_task=%s provider=%s model=%s effort=%s", task, route.provider, route.model, route.effort)
    async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
        for attempt in range(2):
            reserve_call()
            started=time.monotonic()
            try:
                response = await client.post(url, headers=headers, json=body)
            except httpx.TransportError as error:
                record_usage(task,route,body['max_tokens'],error=error,elapsed=time.monotonic()-started,request_characters=request_characters)
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                raise RuntimeError(f"{task}模型网络请求失败") from None
            record_usage(task,route,body['max_tokens'],response=response,elapsed=time.monotonic()-started,request_characters=request_characters)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
            if response.is_error:
                raise service_error(task, response)
            try:
                return completed_text(route, response.json())
            except IncompleteOutputError as error:
                # Discard the partial review. Retry the complete request only for
                # an explicit token limit, with one bounded increase in budget.
                if (task == "review" and attempt == 0
                        and error.reason in {"max_tokens", "length"}
                        and body["max_tokens"] < 8000):
                    body["max_tokens"] = min(8000, body["max_tokens"] * 2)
                    log.warning("review reached output limit; retrying complete review with max_tokens=%d",
                                body["max_tokens"])
                    continue
                raise
            except (ValueError, KeyError, TypeError):
                raise RuntimeError(f"{task}模型响应格式无效") from None
    raise RuntimeError(f"{task}模型请求失败")
