# /root/telegram-schedule-bot/bot/bot.py

import os
import asyncio  # Може знадобитись для асинхронних операцій
from datetime import datetime  # Додано для отримання часу запису
from dotenv import load_dotenv  # Додано для завантаження .env

from aiogram import Bot, Dispatcher, types, F  # Додано F для можливих майбутніх фільтрів
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
# Явний відносний імпорт для модуля в тій самій папці
# Переконайтесь, що google_sheets.py містить всі три функції
from .google_sheets import get_available_dates, update_status, get_gspread_client
# Імпорти фільтрів для Aiogram 3.x
from aiogram.filters import CommandStart, StateFilter

# Завантажуємо змінні оточення з файлу .env
load_dotenv()

# Безпечно отримуємо токен
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ПОМИЛКА: BOT_TOKEN не знайдено в змінних оточення! Перевірте .env файл.")
    exit()  # Вихід, якщо токен не знайдено

# Ініціалізація бота та диспетчера
# В Aiogram 3.x часто використовують Router для кращої структури, але для одного файлу Dispatcher ок
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Визначення станів FSM
class Form(StatesGroup):
    # name = State()        # Стан для імені не використовується у поточній логіці запису на консультацію
    # contact = State()     # Стан для контакту не використовується у поточній логіці запису на консультацію
    service_choice = State()  # Вибір послуги
    phone_number = State()  # Номер для зворотного зв'язку (тільки для опції 1)
    date = State()  # Вибір дати
    time = State()  # Вибір часу
    question = State()  # Питання


# Обробник команди /start (синтаксис Aiogram 3.x)
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()  # Очищуємо попередній стан на випадок перезапуску
    await message.answer(
        "Привіт! Як я можу допомогти?\n"
        "1. Залишити контактні дані, щоб я передзвонив.\n"
        "2. Записатися на платну консультацію."
    )
    await state.set_state(Form.service_choice)


# Обробник вибору послуги (синтаксис Aiogram 3.x з StateFilter)
@dp.message(StateFilter(Form.service_choice))
async def service_choice_handler(message: Message, state: FSMContext):
    choice = message.text.lower()
    # Використовуємо 'in' для більш гнучкого порівняння тексту
    if choice == "1" or "залишити контакт" in choice:
        await state.set_state(Form.phone_number)
        await message.answer("Введіть ваш контакт (телефон або інший спосіб зв'язку):")
    elif choice == "2" or "записатися на консультацію" in choice:
        try:
            available_dates = get_available_dates()
            # Перевірка, чи є взагалі доступні дати
            if not available_dates:
                await message.answer("На жаль, на даний момент немає доступних дат для запису. Спробуйте пізніше.")
                await state.clear()
                return

            dates_str = "\n".join(available_dates.keys())
            await message.answer(f"Ось доступні дати для запису:\n{dates_str}\nВиберіть дату:")
            await state.set_state(Form.date)
        except Exception as e:
            print(f"Помилка отримання доступних дат: {e}")  # Логування помилки на сервері
            await message.answer("Виникла помилка при отриманні списку дат. Спробуйте пізніше або почніть з /start.")
            await state.clear()
    else:
        await message.answer("Будь ласка, оберіть варіант, ввівши '1' або '2'.")


# Обробник отримання контакту (тільки варіант 1) (синтаксис Aiogram 3.x)
@dp.message(StateFilter(Form.phone_number))
async def get_phone_number_handler(message: Message, state: FSMContext):
    contact_info = message.text
    user_id = message.from_user.id
    # Отримуємо ім'я користувача з Telegram, якщо воно є
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"

    try:
        # Зберігаємо контактну інформацію (адаптуйте під вашу логіку google_sheets)
        client = get_gspread_client()
        sheet = client.open("ClientRequests").worksheet("Заявки")  # Або інший аркуш?
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")  # Більш точний час
        # Приклад запису: Ім'я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            message.from_user.full_name or f"User {user_id}",  # Ім'я з ТГ або заглушка
            contact_info,  # Контакт
            "Запит на зворотній дзвінок",  # Тип запиту
            telegram_username,  # Telegram ID/Username
            "",  # Дата (не застосовується)
            "",  # Час (не застосовується)
            timestamp  # Час запису
        ])
        await message.answer(f"Дякую! Ваші контактні дані: '{contact_info}' отримані. Я зв'яжуся з вами.")
    except Exception as e:
        print(f"Помилка збереження контакту в Google Sheets: {e}")
        await message.answer("Виникла помилка під час збереження ваших даних. Будь ласка, спробуйте пізніше.")

    await state.clear()  # Завершуємо діалог


# Обробник вибору дати (варіант 2) (синтаксис Aiogram 3.x)
@dp.message(StateFilter(Form.date))
async def get_date_handler(message: Message, state: FSMContext):
    selected_date = message.text
    try:
        available_dates = get_available_dates()  # Переотримуємо актуальні дані
        if selected_date in available_dates:
            available_times = available_dates[selected_date]
            # Перевірка, чи є вільний час на обрану дату
            if not available_times:
                await message.answer(
                    f"На жаль, на дату {selected_date} вже немає вільного часу. Будь ласка, виберіть іншу дату.")
                # Повторно надсилаємо список дат
                dates_str = "\n".join(available_dates.keys())
                await message.answer(f"Доступні дати для запису:\n{dates_str}\nВиберіть дату:")
                # Залишаємось у тому ж стані Form.date
                return

            await state.update_data(date=selected_date)
            await state.set_state(Form.time)
            times_str = "\n".join(available_times)
            await message.answer(f"Доступні часи на {selected_date}:\n{times_str}\nВиберіть час:")
        else:
            # Якщо введено невірну дату, показуємо доступні
            dates_str = "\n".join(available_dates.keys())
            await message.answer(
                f"Дата '{selected_date}' недоступна або введена невірно. Будь ласка, виберіть одну з доступних дат:\n{dates_str}")
            # Залишаємось у тому ж стані Form.date
    except Exception as e:
        print(f"Помилка отримання/перевірки дати в get_date_handler: {e}")
        await message.answer("Виникла помилка при перевірці дати. Спробуйте, будь ласка, ще раз.")


# Обробник вибору часу (варіант 2) (синтаксис Aiogram 3.x)
@dp.message(StateFilter(Form.time))
async def get_time_handler(message: Message, state: FSMContext):
    selected_time = message.text
    user_data = await state.get_data()
    # Безпечно отримуємо дату зі стану
    selected_date = user_data.get("date")

    # Перевірка, чи є дата у стані (про всяк випадок)
    if not selected_date:
        await message.answer("Виникла помилка стану (не знайдено обрану дату). Будь ласка, почніть спочатку: /start")
        await state.clear()
        return

    try:
        available_dates = get_available_dates()  # Переотримуємо актуальні дані
        # Перевіряємо, чи існує ще така дата і чи доступний обраний час
        if selected_date in available_dates and selected_time in available_dates[selected_date]:
            await state.update_data(time=selected_time)

            # Оновлюємо статус часу в Google Таблиці як "Заброньовано"
            try:
                # Припускаємо, що функція приймає дату, час і новий статус
                update_status(selected_date, selected_time, "Заброньовано")
                # Якщо оновлення статусу пройшло успішно, переходимо до питання
                await state.set_state(Form.question)
                await message.answer(
                    "Час успішно заброньовано!\nТепер, будь ласка, опишіть коротко ваше питання або мету консультації:")
            except Exception as e_update:
                print(f"Помилка оновлення статусу в Google Sheets: {e_update}")
                # Вирішіть, як обробити цю помилку: скасувати бронювання?
                # Поки що просто повідомляємо користувача і НЕ переходимо далі
                await message.answer(
                    "Виникла помилка під час спроби забронювати час у системі. Можливо, хтось встиг раніше. Спробуйте вибрати інший час або почніть з /start.")
                # Повертаємо доступний час на обрану дату
                times_str = "\n".join(available_dates.get(selected_date, []))
                if times_str:
                    await message.answer(f"Доступні часи на {selected_date}:\n{times_str}\nВиберіть час:")
                    await state.set_state(Form.time)  # Повертаємо на вибір часу
                else:  # Якщо часу вже немає
                    await message.answer("На жаль, на цю дату більше немає вільного часу.")
                    await state.clear()

        else:
            # Якщо обраний час вже недоступний або невірний
            times_str = "\n".join(available_dates.get(selected_date, []))
            if times_str:
                await message.answer(
                    f"Час '{selected_time}' на {selected_date} вже зайнятий або введений невірно. Будь ласка, виберіть один з доступних:\n{times_str}")
            else:
                await message.answer(
                    f"На жаль, на {selected_date} більше немає вільного часу. Почніть спочатку: /start")
                await state.clear()
            # Залишаємось у стані Form.time
    except Exception as e:
        print(f"Помилка отримання/перевірки часу в get_time_handler: {e}")
        await message.answer("Виникла помилка при перевірці часу. Спробуйте, будь ласка, ще раз.")


# Обробник отримання питання та збереження заявки (варіант 2) (синтаксис Aiogram 3.x)
@dp.message(StateFilter(Form.question))
async def get_question_handler(message: Message, state: FSMContext):
    question = message.text
    user_data = await state.get_data()
    # Безпечно отримуємо дані зі стану
    selected_date = user_data.get("date")
    selected_time = user_data.get("time")
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"

    # Перевірка, чи всі дані є
    if not selected_date or not selected_time:
        await message.answer("Виникла помилка стану (не знайдено дату або час). Будь ласка, почніть спочатку: /start")
        await state.clear()
        return

    # ЛОГІЧНА ПОМИЛКА В ОРИГІНАЛІ: У цій гілці (варіант 2) ми не питали ім'я та контакт.
    # Використовуємо ім'я з Telegram та username/ID як контакт.
    user_name = message.from_user.full_name or f"User {user_id}"  # Ім'я з ТГ або заглушка
    contact_info = telegram_username  # Контакт - ТГ

    try:
        client = get_gspread_client()
        sheet = client.open("ClientRequests").worksheet("Заявки")
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        # Записуємо рядок згідно з заголовками: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name,  # Ім’я
            contact_info,  # Контакт (з Telegram)
            question,  # Питання
            str(user_id),  # Telegram ID (числове, краще як рядок)
            selected_date,  # Дата консультації
            selected_time,  # Час консультації
            timestamp  # Час, коли зроблено запис
        ])
        await message.answer(f"Дякую! Ваш запис на консультацію ({selected_date} {selected_time}) підтверджено!")
    except Exception as e:
        print(f"Помилка збереження запису в Google Sheets: {e}")
        await message.answer(
            "На жаль, сталася помилка під час фінального збереження вашого запису. Спробуйте пізніше або зв'яжіться з адміністратором.")
        # Тут можна додати логіку для скасування бронювання часу, якщо запис не вдався
        # try: update_status(selected_date, selected_time, "Вільно") except: pass

    await state.clear()  # Завершуємо діалог

# Важливо: Блок запуску polling `if __name__ == '__main__':` НЕ потрібен,
# оскільки додаток запускається через Uvicorn/FastAPI, який керує циклом подій.
