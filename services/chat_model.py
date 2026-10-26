from . import model_config
from openai import OpenAI
from httpx import Timeout
import json
import time
from ..core.error_handling import sanitize
from .credentials import CredentialError, service_error, session
from ..core.localization import language_instruction, t
from ..workflow.prompts import CHAT_SYSTEM_PROMPTS

PROMPT1, PROMPT2, PROMPT3 = CHAT_SYSTEM_PROMPTS

FAILED_MESSAGE = 'An error occurred. Try again later'
MODEL_MAX_ATTEMPTS = 3


class ModelCallError(RuntimeError):
    """The model call failed after a bounded number of attempts."""

    error_code = "MODEL_UNAVAILABLE"

    def __init__(self, message, attempts=MODEL_MAX_ATTEMPTS, model_name=None, request_id=""):
        super().__init__(sanitize(message))
        self.attempts = attempts
        self.model_name = model_name or model_config.TEXT_MODEL
        self.request_id = request_id
        self.phase = "completion"


class ModelResponseFormatError(RuntimeError):
    """The model repeatedly returned unparseable JSON."""

    error_code = "INVALID_JSON"

    def __init__(self, message, attempts=MODEL_MAX_ATTEMPTS, model_name=None,
                 request_id="", response_summary=None):
        super().__init__(sanitize(message))
        self.attempts = attempts
        self.phase = "json_parse"
        self.model_name = model_name or model_config.TEXT_MODEL
        self.request_id = request_id
        self.response_summary = response_summary or {}


class ModelAuthenticationError(ModelCallError):
    """Model authentication or authorization failed; do not retry automatically."""
    error_code = "MODEL_AUTH_FAILED"


class ModelNetworkError(ModelCallError):
    """The model connection failed or timed out."""
    error_code = "MODEL_NETWORK_FAILED"


class ModelQuotaError(ModelCallError):
    """The service rejected requests because of quota or rate limits."""
    error_code = "MODEL_QUOTA_FAILED"


class ModelServerError(ModelCallError):
    """The model server request failed."""
    error_code = "MODEL_SERVER_FAILED"


class ModelEmptyResponseError(ModelCallError):
    """The model returned an empty response."""
    error_code = "MODEL_EMPTY_RESPONSE"


class ModelContractError(ModelResponseFormatError):
    """Parsed business fields do not satisfy the node contract."""
    error_code = "INVALID_CONTRACT"


def validate_object(value, fields):
    """Validate required fields in business nodes, separately from JSON parsing."""
    if not isinstance(value, dict):
        raise ModelContractError('The response must be a JSON object', attempts=1)
    if value.get("error_message"):
        raise ModelContractError(str(value["error_message"]), attempts=1)
    invalid = [key for key, expected in fields.items()
               if key not in value or not isinstance(value[key], expected) or value[key] is None]
    if invalid:
        error = ModelContractError('Missing fields or incorrect field types: ' + ", ".join(invalid), attempts=1)
        error.missing_fields = invalid
        error.phase = "contract_validation"
        raise error
    return value


def _create_text_completion(messages, model_name, max_attempts=MODEL_MAX_ATTEMPTS):
    """Call the text model with up to 3 attempts on failure."""
    messages = [{"role": "system", "content": language_instruction()}] + messages
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            key, generation = session.snapshot()
            with OpenAI(api_key=key, base_url=model_config.BASE_URL, max_retries=0,
                        timeout=Timeout(model_config.TEXT_MODEL_TIMEOUT, connect=model_config.TEXT_MODEL_CONNECT_TIMEOUT)) as client:
                completion = client.chat.completions.create(
                    model=model_name, messages=messages,
                    extra_body={"enable_thinking": model_config.TEXT_MODEL_ENABLE_THINKING},
                )
            session.check_generation(generation)
            content = completion.choices[0].message.content if completion.choices else None
            if not isinstance(content, str) or not content.strip():
                raise ModelEmptyResponseError('The model returned an empty response', attempts=attempt, model_name=model_name)
            return content
        except Exception as exc:
            if isinstance(exc, CredentialError):
                raise
            last_error = exc
            session.check_generation(generation)
            status = getattr(exc, "status_code", 0) or 0
            if status in (401, 402, 403, 404):
                error = service_error(status, getattr(exc, "code", ""))
                if error.error_code == "MODEL_AUTH_FAILED":
                    session.reset()
                raise error from None
            if status and status < 500 and status not in (408, 429):
                raise ModelCallError('The model request was rejected. Check its parameters.', attempts=attempt,
                                     model_name=model_name) from None
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
    status = getattr(last_error, "status_code", 0) or 0
    error_type = (ModelEmptyResponseError if isinstance(last_error, ModelEmptyResponseError)
                  else ModelQuotaError if status == 429
                  else ModelServerError if status else ModelNetworkError)
    raise error_type('The model returned an empty response' if isinstance(last_error, ModelEmptyResponseError)
                     else 'Insufficient quota or rate limit reached. Check balance, quota and request frequency.' if status == 429
                     else 'The model service request failed. Check the network and service status.',
                     attempts=max_attempts, model_name=model_name,
                     request_id=getattr(last_error, "request_id", "")) from None


def chat_with_openai(user_text):
    try:
        return _create_text_completion(
            [
                {'role': 'system', 'content': PROMPT1},
                {'role': 'system', 'content': PROMPT2},
                {'role': 'system', 'content': PROMPT3},
                {'role': 'user', 'content': user_text}
            ],
            model_config.TEXT_MODEL,
        )
    except CredentialError:
        raise
    except Exception:
        return t('The AI model service is temporarily unavailable. Check the network and model configuration and retry.')


def validate_api_key(key):
    """Probe only the configured text model, without author-owned applications."""
    try:
        with OpenAI(api_key=key, base_url=model_config.BASE_URL, max_retries=0,
                    timeout=Timeout(model_config.TEXT_MODEL_TIMEOUT, connect=model_config.TEXT_MODEL_CONNECT_TIMEOUT)) as client:
            response = client.chat.completions.create(
                model=model_config.TEXT_MODEL, messages=[{"role": "user", "content": "Reply OK."}],
                max_tokens=8, extra_body={"enable_thinking": model_config.TEXT_MODEL_ENABLE_THINKING})
            content = response.choices[0].message.content if response.choices else None
            if not isinstance(content, str) or not content.strip():
                raise CredentialError("MODEL_EMPTY_RESPONSE", 'The model returned an empty response. Verify again.')
    except CredentialError:
        raise
    except Exception as exc:
        raise service_error(getattr(exc, "status_code", 0) or 0,
                            getattr(exc, "code", "")) from None

def call_qwen_with_prompt(prompt, model_name=None):
    """Call Qwen with the specified prompt."""
    return _create_text_completion([{'role': 'user', 'content': prompt}], model_name or model_config.TEXT_MODEL)


def call_qwen_json(prompt, model_name=None):
    """Request structured output with up to 3 generations for invalid JSON."""
    model_name = model_name or model_config.TEXT_MODEL
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
        'The model returned unparseable JSON on 3 consecutive attempts', model_name=model_name,
        response_summary={"characters": len(last_text)}
    ) from last_error

def safe_json_loads(text):
    import re
    if not isinstance(text, str):
        raise ValueError('The JSON response must be text')
    text = text.strip()

    # Remove Markdown fences.
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    text = text.strip()

    # Try direct parsing.
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Parse complete containers in occurrence order to avoid treating an array item as the root.
    decoder = json.JSONDecoder()
    for match in re.finditer(r'[\[{]', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            return value
        except json.JSONDecodeError:
            continue

    raise ValueError('Unable to parse the JSON response')
