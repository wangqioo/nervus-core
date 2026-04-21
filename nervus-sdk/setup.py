from setuptools import setup, find_packages

setup(
    name="nervus-sdk",
    version="1.0.0",
    description="Nervus 生态系统 SDK — 5 行代码接入神经网络",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "nats-py[nkeys]>=2.7.0",
        "redis[hiredis]>=5.0.0",
        "asyncpg>=0.29.0",
        "httpx>=0.27.0",
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.30.0",
        "pydantic>=2.7.0",
        "aiofiles>=24.1.0",
    ],
    extras_require={
        "dev": ["pytest", "pytest-asyncio", "httpx"],
    },
)
