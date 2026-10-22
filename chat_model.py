from .model_config import (API_KEY, BASE_URL, TEXT_MODEL, TEXT_MODEL_TIMEOUT,
                           TEXT_MODEL_CONNECT_TIMEOUT, TEXT_MODEL_ENABLE_THINKING)
from dashscope import Application
from openai import OpenAI
from httpx import Timeout
from http import HTTPStatus
import json
import time
from .error_handling import sanitize

PROMPT1 = "你是一个QGIS智能AI助手，你需要向用户提供有关QGIS的任何帮助，包括QGIS相关咨询和自动化QGIS操作等。"
PROMPT2 = "你还具有简单的聊天属性，但若用户的问题与GIS无密切关系，只需要进行一段以内的简短回复，并提醒用户最好只询问QGIS操作等有关问题与要求"
PROMPT3 = "如果用户的问题与GIS相差太远，或违反相关法律法规、守则规范，可以不用回复，并强烈提醒用户不要进行无关的咨询。"

FAILED_MESSAGE = "出错了，请稍后再试"
MODEL_MAX_ATTEMPTS = 3


class ModelCallError(RuntimeError):
    """模型调用经过有限重试后仍然失败。"""

    error_code = "MODEL_UNAVAILABLE"

    def __init__(self, message, attempts=MODEL_MAX_ATTEMPTS, model_name=TEXT_MODEL, request_id=""):
        super().__init__(sanitize(message))
        self.attempts = attempts
        self.model_name = model_name
        self.request_id = request_id
        self.phase = "completion"


class ModelResponseFormatError(RuntimeError):
    """模型连续返回无法解析的JSON。"""

    error_code = "INVALID_JSON"

    def __init__(self, message, attempts=MODEL_MAX_ATTEMPTS, model_name=TEXT_MODEL,
                 request_id="", response_summary=None):
        super().__init__(sanitize(message))
        self.attempts = attempts
        self.phase = "json_parse"
        self.model_name = model_name
        self.request_id = request_id
        self.response_summary = response_summary or {}


class ModelAuthenticationError(ModelCallError):
    """模型认证或授权失败，不自动重试。"""
    error_code = "MODEL_AUTH_FAILED"


class ModelNetworkError(ModelCallError):
    """模型请求连接失败或超时。"""
    error_code = "MODEL_NETWORK_FAILED"


class ModelServerError(ModelCallError):
    """模型服务端请求失败。"""
    error_code = "MODEL_SERVER_FAILED"


class ModelEmptyResponseError(ModelCallError):
    """模型返回空响应。"""
    error_code = "MODEL_EMPTY_RESPONSE"


class ModelContractError(ModelResponseFormatError):
    """解析成功后的业务字段不满足节点契约。"""
    error_code = "INVALID_CONTRACT"


def validate_object(value, fields):
    """在业务节点验证必需字段，不将字段校验混入JSON解析。"""
    if not isinstance(value, dict):
        raise ModelContractError("返回结果必须是JSON对象", attempts=1)
    if value.get("error_message"):
        raise ModelContractError(str(value["error_message"]), attempts=1)
    invalid = [key for key, expected in fields.items()
               if key not in value or not isinstance(value[key], expected) or value[key] is None]
    if invalid:
        error = ModelContractError("缺失字段或字段类型错误：" + ", ".join(invalid), attempts=1)
        error.missing_fields = invalid
        error.phase = "contract_validation"
        raise error
    return value


def _create_text_completion(messages, model_name, max_attempts=MODEL_MAX_ATTEMPTS):
    """调用文本模型，失败时总计尝试3次。"""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            client = OpenAI(
                api_key=API_KEY, base_url=BASE_URL, max_retries=0,
                timeout=Timeout(TEXT_MODEL_TIMEOUT, connect=TEXT_MODEL_CONNECT_TIMEOUT),
            )
            completion = client.chat.completions.create(
                model=model_name, messages=messages,
                extra_body={"enable_thinking": TEXT_MODEL_ENABLE_THINKING},
            )
            content = completion.choices[0].message.content if completion.choices else None
            if not isinstance(content, str) or not content.strip():
                raise ModelEmptyResponseError("模型返回空响应", attempts=attempt, model_name=model_name)
            return content
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status_code", 0) or 0
            if status in (401, 403):
                raise ModelAuthenticationError(str(exc), attempts=attempt, model_name=model_name,
                                               request_id=getattr(exc, "request_id", "")) from exc
            if status and status < 500 and status not in (408, 429):
                raise ModelCallError(str(exc), attempts=attempt, model_name=model_name) from exc
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
    status = getattr(last_error, "status_code", 0) or 0
    error_type = (ModelEmptyResponseError if isinstance(last_error, ModelEmptyResponseError)
                  else ModelServerError if status else ModelNetworkError)
    raise error_type(str(last_error), attempts=max_attempts, model_name=model_name,
                     request_id=getattr(last_error, "request_id", "")) from last_error


def chat_with_openai(user_text):
    try:
        return _create_text_completion(
            [
                {'role': 'system', 'content': PROMPT1},
                {'role': 'system', 'content': PROMPT2},
                {'role': 'system', 'content': PROMPT3},
                {'role': 'user', 'content': user_text}
            ],
            TEXT_MODEL,
        )
    except Exception:
        return "AI模型服务暂时不可用，请检查网络和模型配置后重试。"

def call_qwen_with_prompt(prompt, model_name=TEXT_MODEL):
    """
    使用指定的 Prompt 调用 Qwen 模型
    """
    return _create_text_completion([{'role': 'user', 'content': prompt}], model_name)


def call_qwen_json(prompt, model_name=TEXT_MODEL):
    """请求结构化结果，非法JSON时总计重新生成3次。"""
    last_text = ""
    last_error = None
    for attempt in range(1, MODEL_MAX_ATTEMPTS + 1):
        try:
            last_text = _create_text_completion([{'role': 'user', 'content': prompt}], model_name, max_attempts=1)
            return safe_json_loads(last_text)
        except ModelAuthenticationError:
            raise
        except ModelCallError as exc:
            exc.attempts = attempt
            if type(exc) is ModelCallError or attempt == MODEL_MAX_ATTEMPTS:
                raise
            last_error = exc
        except (ValueError, TypeError) as exc:
            last_error = exc
        if attempt < MODEL_MAX_ATTEMPTS:
            time.sleep(0.5 * attempt)
    raise ModelResponseFormatError(
        "模型连续3次返回无法解析的JSON", model_name=model_name,
        response_summary={"characters": len(last_text)}
    ) from last_error

def safe_json_loads(text):
    import re
    if not isinstance(text, str):
        raise ValueError("JSON响应必须为文本")
    text = text.strip()

    # 去掉markdown
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 按出现顺序解析完整容器，避免把数组内的对象误作根对象。
    decoder = json.JSONDecoder()
    for match in re.finditer(r'[\[{]', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            return value
        except json.JSONDecodeError:
            continue

    raise ValueError("无法解析JSON响应")

# --- 用户目的探测 ---
def detect_user_intent(user_text):
    try:
        response = Application.call(
            # 若没有配置环境变量，可用百炼API Key将下行替换为：api_key="sk-xxx"。但不建议在生产环境中直接将API Key硬编码到代码中，以减少API Key泄露风险。
            api_key=API_KEY,
            app_id='50881ef244034275adaecf8fad01d17e',  # 替换为实际的应用 ID
            prompt=user_text)

        if response.status_code != HTTPStatus.OK:
            print(f'request_id={response.request_id}')
            print(f'code={response.status_code}')
            print(f'message={response.message}')
            print(f'请参考文档：https://help.aliyun.com/zh/model-studio/developer-reference/error-code')
        else:
            return response.output.text
    except Exception as e:
        wrong_message = FAILED_MESSAGE + f"错误信息：{e}"
        return wrong_message
