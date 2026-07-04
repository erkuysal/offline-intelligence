from fastapi import FastAPI

app = FastAPI(
    title="Offline Intelligence Hub API",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Offline Intelligence Hub",
        "version": "0.1.0",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}