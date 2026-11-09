from fastapi import FastAPI

app = FastAPI(
    title="STM32 Smart Parking API",
    description="Backend API for the STM32 Smart Parking system",
    version="0.1.0",
)


@app.get("/api/v1/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "smart-parking-backend",
        "version": "0.1.0",
    }