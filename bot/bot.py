# /root/telegram-schedule-bot/bot/bot.py

import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import sys

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Явний відносний імпорт
from .google_sheets import get_available_dates, update_status, get_gspread_client, SPREADSHEET_NAME, REQUESTS_WORKSHEET_NAME, STATUS_BOOKED, STATUS_FREE # Імпортуємо константи
# Імпорти фільтрів для Aiogram 3.x
from aiogram.filters import CommandStart, StateFilter

# --- Ініціалізація ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ПОМИЛКА: BOT_TOKEN не знайдено в змінних оточення! Перевірте .env файл.", file=sys.stderr)
    exit()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Стани FSM ---
class Form(StatesGroup):
    # Змінюємо стан для імені на два окремих, щоб знати, з якої гілки прийшли
    callback_name = State()  # Ім'я для запиту на дзвінок
    booking_name = State()   # Ім'я для запису на консультацію
    service_choice = State() # Вибір послуги (тепер це перший стан після /start)
    phone_number = State()   # Номер для зворотного зв'язку
    date = State()           # Вибір дати
    time = State()           # Вибір часу
    question = State()       # Питання

# --- Клавіатури ---
# (Функції get_service_choice_keyboard, get_dates_keyboard, get_times_keyboard залишаються БЕЗ ЗМІН з попередньої версії)
def get_service_choice_keyboard():
    """Створює клавіатуру для вибору послуги."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Залишити контакт", callback_data="ask_contact")
    builder.button(text="📅 Записатися на консультацію", callback_data="book_consultation")
    builder.adjust(1)
    return builder.as_markup()

def get_dates_keyboard(dates_dict):
    """Створює клавіатуру з доступними датами."""
    builder = InlineKeyboardBuilder()
    # Сортуємо дати перед відображенням
    sorted_dates = sorted(dates_dict.keys(), key=lambda d: datetime.strptime(d, "%d.%m.%Y").date()) # Припускаємо формат ДД.ММ.РРРР
    for date_str in sorted_dates:
        builder.button(text=date_str, callback_data=f"date_{date_str}")
    builder.adjust(2)
    return builder.as_markup()

def get_times_keyboard(times_list):
    """Створює клавіатуру з доступним часом."""
    builder = InlineKeyboardBuilder()
    # Сортуємо час перед відображенням (якщо потрібно, і якщо формат дозволяє просте сортування рядків)
    for time_str in sorted(times_list):
        builder.button(text=time_str, callback_data=f"time_{time_str}")
    builder.adjust(3)
    return builder.as_markup()

# --- Обробники ---

# Старт бота -> Показуємо кнопки вибору послуги
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    keyboard = get_service_choice_keyboard()
    await message.answer("Привіт! 👋\nЯк я можу допомогти?", reply_markup=keyboard)
    # Встановлюємо стан очікування вибору послуги
    await state.set_state(Form.service_choice)

# Обробка натискання кнопок вибору послуги -> Питаємо ім'я
@dp.callback_query(StateFilter(Form.service_choice))
async def service_choice_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    choice_data = callback.data

    if choice_data == "ask_contact":
        # Питаємо ім'я і переходимо у стан callback_name
        await state.set_state(Form.callback_name)
        await callback.message.edit_text("Добре, я запишу ваші контакти.\nБудь ласка, напишіть ваше ім'я:") # Редагуємо попереднє повідомлення
    elif choice_data == "book_consultation":
        # Питаємо ім'я і переходимо у стан booking_name
        await state.set_state(Form.booking_name)
        await callback.message.edit_text("Добре, запишемо вас на консультацію.\nБудь ласка, напишіть ваше ім'я:") # Редагуємо попереднє повідомлення
    else:
        await callback.message.answer("Невідома опція. Почніть з /start.")
        await state.clear()

# Обробник отримання імені ПІСЛЯ вибору "Залишити контакт" -> Питаємо телефон
@dp.message(StateFilter(Form.callback_name))
async def callback_name_handler(message: Message, state: FSMContext):
    await state.update_data(name=message.text) # Зберігаємо ім'я
    await state.set_state(Form.phone_number)
    await message.answer("Дякую! Тепер введіть ваш контакт (телефон або інший спосіб зв'язку):")

# Обробник отримання імені ПІСЛЯ вибору "Записатися..." -> Показуємо дати
@dp.message(StateFilter(Form.booking_name))
async def booking_name_handler(message: Message, state: FSMContext):
    await state.update_data(name=message.text) # Зберігаємо ім'я
    try:
        available_dates = get_available_dates()
        if not available_dates:
            await message.answer("На жаль, на даний момент немає доступних дат для запису. Спробуйте пізніше.")
            await state.clear()
            return

        keyboard = get_dates_keyboard(available_dates)
        await message.answer("Дякую! Ось доступні дати для запису:\n(дійсні на найближчі 7 днів)\nВиберіть дату:", reply_markup=keyboard)
        await state.set_state(Form.date)
    except Exception as e:
        print(f"Помилка отримання доступних дат (після введення імені): {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("Виникла помилка при отриманні списку дат. Спробуйте пізніше або почніть з /start.")
        await state.clear()

# Обробник отримання контакту (гілка 1) -> Зберігаємо, повертаємось на старт
@dp.message(StateFilter(Form.phone_number))
async def get_phone_number_handler(message: Message, state: FSMContext):
    contact_info = message.text
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}") # Отримуємо ім'я зі стану

    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME) # Перевірте назву аркуша!
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving contact info for {user_name}...", file=sys.stderr)
        # Порядок: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG: Contact info saved.", file=sys.stderr)
        await message.answer(f"Дякую, {user_name}! Ваші контактні дані: '{contact_info}' отримані. Я зв'яжуся з вами.")
        # Повертаємось на старт
        await cmd_start(message, state)
    except Exception as e:
        print(f"Помилка збереження контакту в Google Sheets: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("Виникла помилка під час збереження ваших даних. Будь ласка, спробуйте пізніше.")
        await state.clear() # Очищаємо стан у разі помилки

# Обробка натискання кнопки з датою (гілка 2) -> Показуємо час
@dp.callback_query(StateFilter(Form.date), F.data.startswith("date_"))
async def get_date_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    selected_date = callback.data.split("_")[1]
    try:
        available_dates = get_available_dates()
        if selected_date in available_dates and available_dates[selected_date]:
            available_times = available_dates[selected_date]
            await state.update_data(date=selected_date)
            await state.set_state(Form.time)
            keyboard = get_times_keyboard(available_times)
            await callback.message.edit_text( # Редагуємо повідомлення
                f"Доступні часи на {selected_date}:\nВиберіть час:",
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text("На жаль, ця дата або час на неї вже недоступні. Будь ласка, почніть спочатку з /start.")
            await state.clear()
    except Exception as e:
        print(f"Помилка отримання/перевірки дати (з callback): {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer("Виникла помилка при перевірці дати. Спробуйте ще раз або почніть з /start.")
        await state.clear()

# Обробка натискання кнопки з часом (гілка 2) -> Бронюємо, питаємо питання
@dp.callback_query(StateFilter(Form.time), F.data.startswith("time_"))
async def get_time_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    selected_time = callback.data.split("_")[1]
    user_data = await state.get_data()
    selected_date = user_data.get("date")

    if not selected_date:
        await callback.message.edit_text("Виникла помилка стану (дата). Почніть з /start.")
        await state.clear()
        return

    try:
        current_available_dates = get_available_dates()
        if selected_date in current_available_dates and selected_time in current_available_dates[selected_date]:
            try:
                update_status(selected_date, selected_time, STATUS_BOOKED)
                await state.update_data(time=selected_time)
                await state.set_state(Form.question)
                await callback.message.edit_text( # Редагуємо повідомлення
                    f"Час {selected_date} {selected_time} успішно заброньовано!\nТепер, будь ласка, опишіть коротко ваше питання або мету консультації:"
                )
            except Exception as e_update:
                print(f"Помилка оновлення статусу в Google Sheets під час бронювання: {type(e_update).__name__} - {e_update}", file=sys.stderr)
                await callback.message.edit_text("Виникла помилка під час бронювання часу. Можливо, хтось встиг раніше. Почніть з /start.")
                await state.clear()
        else:
            await callback.message.edit_text(f"На жаль, час {selected_time} на {selected_date} щойно зайняли. Почніть з /start.")
            await state.clear()
    except Exception as e:
        print(f"Помилка отримання/перевірки часу (з callback): {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer("Виникла помилка при перевірці часу. Спробуйте ще раз або почніть з /start.")
        await state.clear()

# Обробник отримання питання та збереження заявки (гілка 2) -> Зберігаємо, надсилаємо деталі, повертаємось на старт
@dp.message(StateFilter(Form.question))
async def get_question_handler(message: Message, state: FSMContext):
    question = message.text
    user_data = await state.get_data()
    # Безпечно отримуємо дані зі стану
    user_name = user_data.get("name", f"User {message.from_user.id}")
    selected_date = user_data.get("date")
    selected_time = user_data.get("time")
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    contact_info = telegram_username # Контакт - ТГ, збережений для запису

    # Перевірка, чи всі дані є
    if not selected_date or not selected_time:
        await message.answer("Виникла помилка стану (не знайдено дату або час). Будь ласка, почніть спочатку: /start")
        await state.clear()
        return

    try:
        # --- Збереження в Google Sheets ---
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME) # Перевірте назву аркуша!
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving appointment for {user_name}...", file=sys.stderr)
        # Порядок: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name, contact_info, question, str(user_id),
            selected_date, selected_time, timestamp
        ])
        print("DEBUG: Appointment saved to Заявки sheet.", file=sys.stderr)

        # --- Повідомлення 1: Підтвердження ---
        await message.answer(f"Дякую, {user_name}! Ваш запис на консультацію ({selected_date} {selected_time}) підтверджено!")

        # --- Повідомлення 2: Деталі та Порядок Консультації ---
        # !!! Важливо: Замініть плейсхолдери на реальні дані !!!
        lawyer_contact_for_booking_questions = "ВАШ_ТЕЛЕФОН_АБО_EMAIL" # Замініть!
        payment_details_text = 'Реквізити для оплати будуть надіслані вам додатково. Оплату необхідно здійснити до початку консультації.' # Замініть або уточніть!

        # Використовуємо HTML для форматування, але ЗАМІНЮЄМО <br> на \n
        details_text_html = (
            f"🗓️ <b>Деталі вашого запису:</b> {selected_date} о {selected_time}.\n\n"  # Замість <br>
            f"<b>Порядок проведення онлайн-консультації:</b>\n\n"  # Замість <br>
            f"1️⃣ <b>Платформа:</b> Ми зв'яжемося з вами незадовго до початку за контактом (<code>{contact_info}</code>), щоб узгодити зручну платформу (Zoom, Google Meet, Teams, Viber, WhatsApp, Telegram тощо) та надати посилання.\n\n"  # Замість <br>
            f"2️⃣ <b>Підготовка:</b> Якщо ваше питання стосується документів, підготуйте їх копії/фото. Будь ласка, забезпечте стабільний інтернет та тихе місце.\n\n"  # Замість <br>
            f"3️⃣ <b>Оплата:</b> Вартість - <b>1000 грн/год</b>. {payment_details_text}\n\n"  # Замість <br>
            f"4️⃣ <b>Консультація:</b> Будьте готові обговорити ваше питання. Адвокат Меркович Богдан надасть вам необхідні роз'яснення та рекомендації.\n\n"  # Замість <br>
            f"5️⃣ <b>Зв'язок:</b> З термінових питань щодо запису <i>до</i> консультації звертайтесь: {lawyer_contact_for_booking_questions}.\n\n"  # Замість <br>
            f"Очікуйте на зв'язок для узгодження платформи!"
        )
        # Надсилаємо повідомлення з HTML розміткою, parse_mode залишається HTML
        print("DEBUG: Attempting to send details message...", file=sys.stderr)
        await message.answer(details_text_html, parse_mode="HTML")
        print("DEBUG: Details message sent.", file=sys.stderr)

        # --- Повернення на старт ---
        print("DEBUG: Returning to start after successful booking and sending details.", file=sys.stderr)
        # Викликаємо стартовий обробник, який очистить стан і почне діалог заново
        await cmd_start(message, state)

    except Exception as e:
        print(f"Помилка збереження запису консультації в Google Sheets: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("На жаль, сталася помилка під час фінального збереження вашого запису. Будь ласка, спробуйте ще раз пізніше або зв'яжіться з адміністратором.")
        # У разі помилки збереження, також очищуємо стан
        await state.clear()

    # state.clear() тут вже не потрібен, якщо cmd_start викликається успішно