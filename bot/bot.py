# /root/telegram-schedule-bot/bot/bot.py
# Этот файл отвечает за инициализацию основных объектов бота и загрузку конфигурации.

import os
import sys
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher

# --- Загрузка конфигурации ---
print("DEBUG [bot.py]: Попытка загрузить файл .env...", file=sys.stderr)

# Определяем путь к корневой папке проекта относительно текущего файла
# __file__ -> bot/bot.py
# os.path.dirname(__file__) -> bot/
# os.path.dirname(os.path.dirname(__file__)) -> telegram-schedule-bot/ (корень проекта)
current_script_path = os.path.abspath(__file__)
bot_package_dir = os.path.dirname(current_script_path)
project_root_dir = os.path.dirname(bot_package_dir) # Это корень вашего проекта
dotenv_path = os.path.join(project_root_dir, '.env')

if os.path.exists(dotenv_path):
    print(f"DEBUG [bot.py]: Загрузка .env из явного пути: {dotenv_path}", file=sys.stderr)
    load_dotenv(dotenv_path=dotenv_path)
else:
    if load_dotenv(): # Попытка загрузить из стандартных мест
        print("DEBUG [bot.py]: Файл .env успешно загружен через стандартный load_dotenv().", file=sys.stderr)
    else:
        print(f"ПРЕДУПРЕЖДЕНИЕ [bot.py]: Файл .env не найден по пути {dotenv_path} или через стандартный поиск. "
              "Бот будет полагаться на переменные окружения, установленные иным образом.", file=sys.stderr)

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_CHAT_ID_STR = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = None # Инициализируем с None
if ADMIN_CHAT_ID_STR:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_STR)
        print(f"DEBUG [bot.py]: ADMIN_CHAT_ID установлен: {ADMIN_CHAT_ID}", file=sys.stderr)
    except ValueError:
        print(f"ОШИБКА [bot.py]: ADMIN_CHAT_ID ('{ADMIN_CHAT_ID_STR}') в .env или окружении не является числом! "
              "Уведомления админу будут отключены.", file=sys.stderr)
        ADMIN_CHAT_ID = None
else:
    print("ПРЕДУПРЕЖДЕНИЕ [bot.py]: ADMIN_CHAT_ID не найден в .env или окружении. "
          "Уведомления админу будут отключены.", file=sys.stderr)

if not BOT_TOKEN:
    error_message = "КРИТИЧЕСКАЯ ОШИБКА [bot.py]: BOT_TOKEN не настроен в .env или окружении! Бот не может запуститься."
    print(error_message, file=sys.stderr)
    raise ValueError(error_message)

# --- Инициализация Bot и Dispatcher ---
print("DEBUG [bot.py]: Попытка инициализации Bot и Dispatcher...", file=sys.stderr)
try:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    print("DEBUG [bot.py]: Bot и Dispatcher успешно инициализированы.", file=sys.stderr)
except Exception as e:
    error_message = f"КРИТИЧЕСКАЯ ОШИБКА [bot.py]: Не удалось инициализировать Bot/Dispatcher: {e}. Проверьте BOT_TOKEN."
    print(error_message, file=sys.stderr)
    raise RuntimeError(error_message) from e

# DATE_FORMAT_IN_SHEET теперь будет импортироваться из google_sheets.py в тех модулях, где он нужен (keyboards.py, handlers.py)
