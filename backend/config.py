import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DATA_DIR, "gitter.db")
PROJECTS_ROOT = os.path.join(DATA_DIR, "projects")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
GRAPHIFY_DIR = os.path.join(DATA_DIR, "graphify")
GLOBAL_WIKI_DIR = os.path.join(DATA_DIR, "global-wiki")
GLOBAL_WIKI_SOURCES_DIR = os.path.join(GLOBAL_WIKI_DIR, "sources")
GLOBAL_WIKI_WIKI_DIR = os.path.join(GLOBAL_WIKI_DIR, "wiki")
GLOBAL_WIKI_META_DIR = os.path.join(GLOBAL_WIKI_DIR, ".llm-wiki")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

MAX_UPLOAD_SIZE = 1024 * 1024 * 1024

PROVIDER_ENV_MAP = {
    "openai": {"key": "OPENAI_API_KEY", "base": "OPENAI_BASE_URL", "models": "OPENAI_MODELS"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "base": "ANTHROPIC_BASE_URL", "models": "ANTHROPIC_MODELS"},
    "google": {"key": "GOOGLE_API_KEY", "base": "GOOGLE_BASE_URL", "models": "GOOGLE_MODELS"},
    "deepseek": {"key": "DEEPSEEK_API_KEY", "base": "DEEPSEEK_BASE_URL", "models": "DEEPSEEK_MODELS"},
    "qwen": {"key": "QWEN_API_KEY", "base": "QWEN_BASE_URL", "models": "QWEN_MODELS"},
    "kimi": {"key": "KIMI_API_KEY", "base": "KIMI_BASE_URL", "models": "KIMI_MODELS"},
    "minimax": {"key": "MINIMAX_API_KEY", "base": "MINIMAX_BASE_URL", "models": "MINIMAX_MODELS"},
    "glm": {"key": "GLM_API_KEY", "base": "GLM_BASE_URL", "models": "GLM_MODELS"},
    "siliconflow": {"key": "SILICONFLOW_API_KEY", "base": "SILICONFLOW_BASE_URL", "models": "SILICONFLOW_MODELS"},
    "doubao": {"key": "DOUBAO_API_KEY", "base": "DOUBAO_BASE_URL", "models": "DOUBAO_MODELS"},
    "openrouter": {"key": "OPENROUTER_API_KEY", "base": "OPENROUTER_BASE_URL", "models": "OPENROUTER_MODELS"},
    "grok": {"key": "GROK_API_KEY", "base": "GROK_BASE_URL", "models": "GROK_MODELS"},
    "tencent": {"key": "TENCENT_API_KEY", "base": "TENCENT_BASE_URL", "models": "TENCENT_MODELS"},
    "xiaomi": {"key": "XIAOMI_API_KEY", "base": "XIAOMI_BASE_URL", "models": "XIAOMI_MODELS"},
}
