from fastapi import FastAPI

app = FastAPI(
    title="Network Simulator Backend",
    description=(
        "Backend API for an AI-powered 3D network learning and troubleshooting simulator."
    ),
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
