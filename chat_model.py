from .model_config import API_KEY, BASE_URL, TEXT_MODEL
from dashscope import Application
from openai import OpenAI
from http import HTTPStatus
import json

PROMPT1 = "你是一个QGIS智能AI助手，你需要向用户提供有关QGIS的任何帮助，包括QGIS相关咨询和自动化QGIS操作等。"
PROMPT2 = "你还具有简单的聊天属性，但若用户的问题与GIS无密切关系，只需要进行一段以内的简短回复，并提醒用户最好只询问QGIS操作等有关问题与要求"
PROMPT3 = "如果用户的问题与GIS相差太远，或违反相关法律法规、守则规范，可以不用回复，并强烈提醒用户不要进行无关的咨询。"

FAILED_MESSAGE = "出错了，请稍后再试"


def chat_with_openai(user_text):
    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )

        completion = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {'role': 'system', 'content': PROMPT1},
                {'role': 'system', 'content': PROMPT2},
                {'role': 'system', 'content': PROMPT3},
                {'role': 'user', 'content': user_text}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        error_str = str(e)
        if "Arrearage" in error_str or "Access denied" in error_str:
            return "聊天接口报错: 阿里云 API Key 已欠费或无效，请检查配置。"
        return f"聊天接口报错: {error_str}"

def call_qwen_with_prompt(prompt, model_name=TEXT_MODEL):
    """
    使用指定的 Prompt 调用 Qwen 模型
    """
    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )

        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {'role': 'user', 'content': prompt}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        error_str = str(e)
        if "Arrearage" in error_str or "Access denied" in error_str:
            return "聊天接口报错: 阿里云 API Key 已欠费或无效，请检查配置。"
        raise Exception(f"聊天接口报错: {error_str}")

def safe_json_loads(text):
    import re
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
    except:
        pass

    # 提取JSON - 优先匹配对象 {}
    match = re.search(r'\{.*\}', text, re.S)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    match = re.search(r'\[.*\]', text, re.S)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    raise Exception(f"无法解析JSON: {text}")

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
