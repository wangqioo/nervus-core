import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/data/files"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LLAMA_URL = os.getenv("LLAMA_URL", "http://nervus-llama:8080")

# ZhipuAI fallback — 若设置了 GLM_API_KEY，优先用 GLM 做分析
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4-flash")
GLM_VISION_MODEL = os.getenv("GLM_VISION_MODEL", "glm-4v-flash")

# LinkBox API — 可选的链接解析增强
LINKBOX_API_URL = os.getenv("LINKBOX_API_URL", "")
LINKBOX_API_KEY = os.getenv("LINKBOX_API_KEY", "")

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"},
    "video": {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"},
    "document": {".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".xls", ".xlsx", ".ppt", ".pptx"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
}

URL_PATTERNS = {
    "wechat": ["mp.weixin.qq.com"],
    "bilibili": ["bilibili.com", "b23.tv"],
}
