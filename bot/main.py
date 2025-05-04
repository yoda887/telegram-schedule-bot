import asyncio
from fastapi import FastAPI
from .bot import dp, bot

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot))

