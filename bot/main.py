# /root/telegram-schedule-bot/main.py
import asyncio
import sys
from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn  # Для запуска из командной строки, если нужно

# Импортируем bot и dp из bot.bot
from .bot import bot, dp
# Импортируем главный роутер из bot.handlers
from .handlers import main_router  # Убедитесь, что main_router экспортируется из bot/handlers.py

print("DEBUG [main.py]: Инициализация FastAPI приложения...", file=sys.stderr)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO [main.py]: Запуск FastAPI приложения...", file=sys.stderr)
    print("INFO [main.py]: Регистрация Aiogram роутеров...", file=sys.stderr)

    # Регистрируем наш главный роутер (который содержит все остальные хендлеры)
    dp.include_router(main_router)
    print("INFO [main.py]: Aiogram роутеры зарегистрированы.", file=sys.stderr)

    print("INFO [main.py]: Запуск Telegram бота (polling)...", file=sys.stderr)
    # Запускаем polling Aiogram в фоновом режиме
    # skip_updates=True - пропускаем старые сообщения при старте
    asyncio.create_task(dp.start_polling(bot, skip_updates=True))

    yield  # Приложение FastAPI работает здесь

    # Код ниже выполнится при остановке FastAPI
    print("INFO [main.py]: Остановка FastAPI приложения...", file=sys.stderr)
    print("INFO [main.py]: Остановка Telegram бота (polling)...", file=sys.stderr)
    await dp.stop_polling()
    await bot.session.close()  # Важно для корректного закрытия сессии бота
    print("INFO [main.py]: Aiogram polling остановлен, сессия закрыта.", file=sys.stderr)


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def read_root():
    return {"message": "Lawyer Bot FastAPI is running. Bot is polling."}


# Блок для запуска Uvicorn, если этот файл запускается напрямую
# (например, python main.py)
# На сервере вы, вероятно, будете запускать через systemd:
# uvicorn main:app --host 0.0.0.0 --port 8000
if __name__ == "__main__":
    # Убедитесь, что uvicorn установлен в вашем venv
    # pip install uvicorn[standard]
    print("INFO [main.py]: Запуск Uvicorn сервера из main.py...", file=sys.stderr)
    # Путь к приложению для Uvicorn теперь будет 'main:app'
    # если вы запускаете `python main.py` из корня проекта.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
