"""
Nervus Whisper Service
本地离线语音转写，基于 faster-whisper
端口：8081
"""

import os
import tempfile
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nervus.whisper")

# 配置
MODEL_NAME = os.getenv("WHISPER_MODEL", "medium")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")          # "cuda" on Jetson
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
MODEL_DIR = os.getenv("WHISPER_MODEL_DIR", "/models")
PORT = int(os.getenv("WHISPER_PORT", "8081"))

model: WhisperModel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    logger.info(f"加载 Whisper 模型: {MODEL_NAME} ({DEVICE}/{COMPUTE_TYPE})")
    model = WhisperModel(
        MODEL_NAME,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        download_root=MODEL_DIR,
    )
    logger.info("Whisper 模型就绪")
    yield
    logger.info("Whisper 服务关闭")


app = FastAPI(
    title="Nervus Whisper Service",
    description="本地离线语音转写",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = "zh",
    task: str = "transcribe",  # "transcribe" or "translate"
):
    """
    转写音频文件为文字。
    支持格式：mp3, wav, m4a, ogg, flac, mp4
    返回：{ text, segments, language, duration }
    """
    if model is None:
        raise HTTPException(status_code=503, detail="模型未就绪")

    # 保存上传文件到临时目录
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        logger.info(f"开始转写: {file.filename} ({len(content) / 1024:.1f} KB)")

        segments_gen, info = model.transcribe(
            tmp_path,
            language=language,
            task=task,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        segments = []
        full_text = []
        for seg in segments_gen:
            segments.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            })
            full_text.append(seg.text.strip())

        result = {
            "text": " ".join(full_text),
            "segments": segments,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 2),
        }

        logger.info(f"转写完成: {len(full_text)} 段，时长 {info.duration:.1f}s")
        return JSONResponse(result)

    finally:
        os.unlink(tmp_path)


@app.post("/transcribe/base64")
async def transcribe_base64(body: dict):
    """
    接收 base64 编码的音频数据转写。
    body: { audio_b64: str, format: str, language: str }
    """
    import base64

    if model is None:
        raise HTTPException(status_code=503, detail="模型未就绪")

    audio_b64 = body.get("audio_b64", "")
    fmt = body.get("format", "wav")
    language = body.get("language", "zh")

    if not audio_b64:
        raise HTTPException(status_code=400, detail="audio_b64 不能为空")

    audio_bytes = base64.b64decode(audio_b64)

    with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments_gen, info = model.transcribe(
            tmp_path,
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        segments = []
        full_text = []
        for seg in segments_gen:
            segments.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            })
            full_text.append(seg.text.strip())

        return {
            "text": " ".join(full_text),
            "segments": segments,
            "language": info.language,
            "duration": round(info.duration, 2),
        }
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
