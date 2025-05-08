# /root/telegram-schedule-bot/bot/bot.py

import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import sys  # Для логування помилок в stderr

# Імпорти Aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import CommandStart, StateFilter

# Імпорт функцій та констант з нашого модуля google_sheets
# Переконайтесь, що всі ці функції та константи існують у вашому google_sheets.py
from .google_sheets import (
    get_available_dates,
    update_status,
    get_gspread_client,
    get_client_provided_name,  # Нова функція для отримання імені
    save_or_update_client_name,  # Нова функція для збереження імені
    SPREADSHEET_NAME,
    REQUESTS_WORKSHEET_NAME,
    SCHEDULE_WORKSHEET_NAME,
    STATUS_BOOKED,
    STATUS_FREE,
    DATE_FORMAT_IN_SHEET
)

# --- Ініціалізація ---
load_dotenv()  # Завантажуємо змінні з .env файлу

BOT_TOKEN = os.getenv("BOT_TOKEN")

# !!! НОВЕ: Завантажуємо ID адміна !!!
ADMIN_CHAT_ID_STR = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = None # За замовчуванням None
if ADMIN_CHAT_ID_STR:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_STR) # Перетворюємо на число
        print(f"DEBUG: Admin chat ID loaded: {ADMIN_CHAT_ID}", file=sys.stderr)
    except ValueError:
        print(f"ПОМИЛКА: ADMIN_CHAT_ID ('{ADMIN_CHAT_ID_STR}') в .env файлі не є числом! Сповіщення адміну вимкнено.", file=sys.stderr)
else:
    print("ПОПЕРЕДЖЕННЯ: ADMIN_CHAT_ID не знайдено в .env файлі! Сповіщення адміну вимкнено.", file=sys.stderr)


if not BOT_TOKEN:
    # Використовуємо sys.stderr для логів помилок
    print("ПОМИЛКА: BOT_TOKEN не знайдено в змінних оточення! Перевірте .env файл.", file=sys.stderr)
    exit()  # Критична помилка, виходимо

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- Стани FSM ---
class Form(StatesGroup):
    # Стани для різних шляхів збору імені
    callback_name = State()  # Ім'я для запиту на дзвінок
    booking_name = State()  # Ім'я для запису на консультацію
    # Інші стани
    service_choice = State()  # Вибір послуги
    phone_number = State()  # Номер для зворотного зв'язку
    date = State()  # Вибір дати
    time = State()  # Вибір часу
    question = State()  # Питання


# --- Клавіатури ---

def get_service_choice_keyboard():
    """Створює клавіатуру для вибору послуги."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Залишити контакт", callback_data="ask_contact")
    builder.button(text="📅 Записатися на консультацію", callback_data="book_consultation")
    builder.adjust(1)
    return builder.as_markup()


def get_dates_keyboard(dates_dict):
    """Створює клавіатуру з доступними датами та кнопкою 'Назад'."""
    builder = InlineKeyboardBuilder()
    try:
        sorted_dates = sorted(dates_dict.keys(),
                              key=lambda d_str: datetime.strptime(d_str, DATE_FORMAT_IN_SHEET).date())
    except Exception as e_sort:
        print(f"Error sorting dates in get_dates_keyboard: {e_sort}. Using unsorted keys.", file=sys.stderr)
        sorted_dates = list(dates_dict.keys())  # Fallback

    for date_str in sorted_dates:
        builder.button(text=date_str, callback_data=f"date_{date_str}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service_choice_from_date"))
    return builder.as_markup()


def get_times_keyboard(times_list):
    """Створює клавіатуру з доступним часом та кнопкою 'Назад'."""
    builder = InlineKeyboardBuilder()
    for time_str in sorted(times_list):  # Просте сортування рядків часу
        builder.button(text=time_str, callback_data=f"time_{time_str}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date_selection"))
    return builder.as_markup()


def get_share_contact_keyboard():
    """Створює клавіатуру відповіді для запиту номера телефону."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Поділитися моїм номером телефону", request_contact=True)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# --- Допоміжна функція для показу меню вибору послуг ---
async def show_service_choice_menu(target_message_or_callback: types.TelegramObject, state: FSMContext,
                                   user_name: str = None):
    """Показує меню вибору послуг, редагуючи повідомлення або надсилаючи нове."""
    await state.set_state(Form.service_choice)  # Встановлюємо правильний стан
    keyboard = get_service_choice_keyboard()
    text = f"Привіт, {user_name}! 👋\nЯк я можу допомогти?" if user_name else "Привіт! 👋\nЯк я можу допомогти?"

    if isinstance(target_message_or_callback, CallbackQuery):
        # Якщо це відповідь на колбек, намагаємося редагувати
        try:
            await target_message_or_callback.message.edit_text(text, reply_markup=keyboard)
        except Exception as e_edit:
            print(f"DEBUG: Could not edit message, sending new one. Error: {e_edit}", file=sys.stderr)
            # Якщо редагування не вдалося, надсилаємо нове повідомлення
            await target_message_or_callback.message.answer(text, reply_markup=keyboard)
    elif isinstance(target_message_or_callback, Message):
        # Якщо це звичайне повідомлення, надсилаємо нове
        await target_message_or_callback.answer(text, reply_markup=keyboard)


# --- Обробники ---

# Обробник команди /start
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, remembered_name: str = None):
    """
    Обробляє команду /start.
    Перевіряє, чи є збережене ім'я користувача, і показує меню вибору послуг.
    """
    await state.clear()  # Завжди очищуємо стан на старті
    user_id = message.from_user.id
    stored_name = None

    if not remembered_name:  # Якщо ім'я не передано з попереднього циклу
        try:
            # Намагаємося отримати ім'я з Google Sheets
            stored_name = get_client_provided_name(user_id)
        except Exception as e:
            print(f"ERROR checking for stored client name: {type(e).__name__} - {e}", file=sys.stderr)
            # Продовжуємо без імені, якщо сталася помилка Sheets

    # Використовуємо ім'я, передане з попереднього циклу, якщо воно є
    display_name = remembered_name or stored_name

    if display_name:
        # Якщо маємо ім'я (з бази або передане), зберігаємо його в FSM для цієї сесії
        await state.update_data(name=display_name)

    # Показуємо меню вибору послуг
    await show_service_choice_menu(message, state, display_name)


# Обробка натискання кнопок вибору послуги -> Перехід до запиту імені
@dp.callback_query(StateFilter(Form.service_choice))
async def service_choice_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # Відповідаємо на колбек
    choice_data = callback.data

    # Прибираємо кнопки з повідомлення, на яке натиснули
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e_edit:
        print(f"DEBUG: Could not edit reply markup in service_choice: {e_edit}", file=sys.stderr)

    if choice_data == "ask_contact":
        await state.set_state(Form.callback_name)
        await callback.message.answer("Добре, я запишу ваші контакти.\nБудь ласка, напишіть ваше ім'я:")
    elif choice_data == "book_consultation":
        await state.set_state(Form.booking_name)
        await callback.message.answer("Добре, запишемо вас на консультацію.\nБудь ласка, напишіть ваше ім'я:")
    else:
        # Якщо раптом прийшов невідомий callback_data
        await callback.message.answer("Невідома опція. Будь ласка, почніть з /start.")
        await state.clear()


# Обробник отримання імені (гілка "Залишити контакт") -> Питаємо телефон
@dp.message(StateFilter(Form.callback_name))
async def callback_name_handler(message: Message, state: FSMContext):
    user_name = message.text
    await state.update_data(name=user_name)  # Зберігаємо ім'я у FSM

    # Зберігаємо/оновлюємо ім'я в Google Sheets
    user_id = message.from_user.id
    tg_username = message.from_user.username  # Може бути None
    try:
        save_or_update_client_name(user_id, tg_username, user_name)
    except Exception as e:
        print(f"ERROR saving client name (callback flow): {type(e).__name__} - {e}", file=sys.stderr)
        # Не перериваємо потік через помилку збереження імені

    await state.set_state(Form.phone_number)
    keyboard = get_share_contact_keyboard()
    await message.answer(
        f"Дякую, {user_name}! Тепер, будь ласка, поділіться вашим номером телефону, натиснувши кнопку нижче, "
        "або введіть ваш контакт (телефон або інший спосіб зв'язку) вручну:",
        reply_markup=keyboard
    )


# Обробник отримання імені (гілка "Записатися...") -> Показуємо дати
@dp.message(StateFilter(Form.booking_name))
async def booking_name_handler(message: Message, state: FSMContext):
    user_name = message.text
    await state.update_data(name=user_name)  # Зберігаємо ім'я у FSM

    # Зберігаємо/оновлюємо ім'я в Google Sheets
    user_id = message.from_user.id
    tg_username = message.from_user.username  # Може бути None
    try:
        save_or_update_client_name(user_id, tg_username, user_name)
    except Exception as e:
        print(f"ERROR saving client name (booking flow): {type(e).__name__} - {e}", file=sys.stderr)
        # Не перериваємо потік

    # Показуємо доступні дати
    try:
        print(f"DEBUG: User {user_name} selected booking. Getting available dates...", file=sys.stderr)
        available_dates = get_available_dates()
        if not available_dates:
            await message.answer(
                f"На жаль, {user_name}, на даний момент немає доступних дат для запису. Спробуйте пізніше.")
            await state.clear()
            await show_service_choice_menu(message, state, user_name)  # Повертаємо на вибір послуги
            return

        keyboard = get_dates_keyboard(available_dates)
        await message.answer(
            f"Дякую, {user_name}! Ось доступні дати для запису:\n(дійсні на найближчі 7 днів)\nВиберіть дату:",
            reply_markup=keyboard)
        await state.set_state(Form.date)
    except Exception as e:
        print(f"Помилка отримання доступних дат для {user_name}: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("Виникла помилка при отриманні списку дат. Спробуйте пізніше або почніть з /start.")
        await state.clear()


# Обробник отримання пошареного контакту (гілка 1)
@dp.message(StateFilter(Form.phone_number), F.contact)
async def contact_shared_handler(message: Message, state: FSMContext):
    contact_info = message.contact.phone_number
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")  # Отримуємо ім'я зі стану

    # Зберігаємо отриманий контакт у стані (можливо, не обов'язково, якщо одразу пишемо в таблицю)
    await state.update_data(contact=contact_info)

    try:
        # Зберігаємо дані в Google Sheets
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving SHARED contact info for {user_name} - {contact_info}...", file=sys.stderr)
        # Порядок: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт пошарено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG: SHARED contact info saved.", file=sys.stderr)

        # --- Надсилання сповіщення адміну ---
        if ADMIN_CHAT_ID:  # Надсилаємо, тільки якщо ID адміна вказано
            notification_text = (
                f"🔔 **Новий запит на дзвінок (Контакт пошарено)**\n\n"
                f"👤 **Ім'я:** {user_name}\n"
                f"📞 **Контакт:** `{contact_info}`\n"  # Використовуємо ` для копіювання номера
                f"💬 **Telegram:** {telegram_username} (ID: {user_id})\n"
                f"⏰ **Час запиту:** {timestamp}"
            )
            try:
                await bot.send_message(ADMIN_CHAT_ID, notification_text,
                                       parse_mode="MarkdownV2")  # Використовуємо Markdown
                print(f"DEBUG: Sent shared contact notification to admin chat {ADMIN_CHAT_ID}", file=sys.stderr)
            except Exception as e_notify:
                # Логуємо помилку надсилання сповіщення, але не перериваємо користувача
                print(
                    f"ERROR: Could not send shared contact notification to admin {ADMIN_CHAT_ID}: {type(e_notify).__name__} - {e_notify}",
                    file=sys.stderr)
        # ------------------------------------



        # Надсилаємо підтвердження і прибираємо клавіатуру
        await message.answer(
            f"Дякую, {user_name}! Ваш номер телефону: {contact_info} отримано.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        # Повертаємось на старт, передаючи відоме ім'я
        await cmd_start(message, state, remembered_name=user_name)
    except Exception as e:
        print(f"Помилка збереження SHARED контакту: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer(
            "Виникла помилка під час збереження ваших даних. Спробуйте пізніше.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.clear()


# Обробник отримання контакту текстом (гілка 1)
@dp.message(StateFilter(Form.phone_number), F.text)
async def get_phone_number_text_handler(message: Message, state: FSMContext):
    contact_info = message.text  # Користувач ввів контакт вручну
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")

    # Зберігаємо введений контакт у стані
    await state.update_data(contact=contact_info)

    try:
        # Зберігаємо дані в Google Sheets
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving TYPED contact info for {user_name} - {contact_info}...", file=sys.stderr)
        # Порядок: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт введено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG: TYPED contact info saved.", file=sys.stderr)

        # --- Надсилання сповіщення адміну ---
        if ADMIN_CHAT_ID:
            notification_text = (
                f"🔔 **Новий запит на дзвінок (Контакт введено)**\n\n"
                f"👤 **Ім'я:** {user_name}\n"
                f"📞 **Контакт:** {contact_info}\n"  # Не беремо в ``, бо може бути не телефон
                f"💬 **Telegram:** {telegram_username} (ID: {user_id})\n"
                f"⏰ **Час запиту:** {timestamp}"
            )
            try:
                await bot.send_message(ADMIN_CHAT_ID, notification_text, parse_mode="MarkdownV2")
                print(f"DEBUG: Sent typed contact notification to admin chat {ADMIN_CHAT_ID}", file=sys.stderr)
            except Exception as e_notify:
                print(
                    f"ERROR: Could not send typed contact notification to admin {ADMIN_CHAT_ID}: {type(e_notify).__name__} - {e_notify}",
                    file=sys.stderr)
        # ------------------------------------


        # Надсилаємо підтвердження і прибираємо клавіатуру
        await message.answer(
            f"Дякую, {user_name}! Ваші контактні дані: '{contact_info}' отримані. Я зв'яжуся з вами.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        # Повертаємось на старт, передаючи відоме ім'я
        await cmd_start(message, state, remembered_name=user_name)
    except Exception as e:
        print(f"Помилка збереження TYPED контакту: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer(
            "Виникла помилка під час збереження ваших даних. Будь ласка, спробуйте пізніше.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.clear()


# --- Обробники кнопок "Назад" ---
@dp.callback_query(F.data == "back_to_service_choice_from_date", StateFilter(Form.date))
async def back_to_service_choice_from_date_handler(callback: CallbackQuery, state: FSMContext):
    """Повертає користувача до вибору послуги з меню вибору дати."""
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")
    # Показуємо меню вибору послуг, редагуючи поточне повідомлення
    await show_service_choice_menu(callback, state, user_name)


@dp.callback_query(F.data == "back_to_date_selection", StateFilter(Form.time))
async def back_to_date_selection_handler(callback: CallbackQuery, state: FSMContext):
    """Повертає користувача до вибору дати з меню вибору часу."""
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")  # Ім'я вже має бути в стані
    try:
        available_dates = get_available_dates()
        if not available_dates:
            # Якщо раптом доступних дат не стало, повертаємо на головне меню
            await callback.message.edit_text("На жаль, на даний момент немає доступних дат. Повертаю на головне меню.")
            await show_service_choice_menu(callback, state, user_name)
            return

        keyboard = get_dates_keyboard(available_dates)
        # Редагуємо повідомлення, показуючи дати
        await callback.message.edit_text(
            f"{user_name}, ось доступні дати для запису:\n(дійсні на найближчі 7 днів)\nВиберіть дату:",
            reply_markup=keyboard
        )
        await state.set_state(Form.date)  # Встановлюємо стан вибору дати
    except Exception as e:
        print(f"Помилка в back_to_date_selection_handler: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.edit_text("Виникла помилка. Повертаю на головне меню.")
        await show_service_choice_menu(callback, state, user_name)


# --- Обробники вибору дати, часу, питання ---

@dp.callback_query(StateFilter(Form.date), F.data.startswith("date_"))
async def get_date_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    selected_date = callback.data.split("date_")[1]
    try:
        available_dates = get_available_dates()  # Отримуємо актуальні дані
        if selected_date in available_dates and available_dates[selected_date]:
            available_times = available_dates[selected_date]
            await state.update_data(date=selected_date)
            await state.set_state(Form.time)
            keyboard = get_times_keyboard(available_times)
            await callback.message.edit_text(  # Редагуємо повідомлення
                f"Доступні часи на {selected_date}:\nВиберіть час:",
                reply_markup=keyboard
            )
        else:
            # Дату вже зайняли або вона стала недійсною - оновлюємо кнопки дат
            keyboard = get_dates_keyboard(available_dates)
            await callback.message.edit_text(
                "На жаль, ця дата або час на неї вже недоступні. Спробуйте вибрати іншу або натисніть 'Назад'.",
                reply_markup=keyboard
            )
            await state.set_state(Form.date)  # Залишаємось у стані вибору дати
    except Exception as e:
        print(f"Помилка отримання/перевірки дати (callback): {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer("Виникла помилка. Почніть з /start.")
        await state.clear()


@dp.callback_query(StateFilter(Form.time), F.data.startswith("time_"))
async def get_time_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    selected_time = callback.data.split("time_")[1]
    user_data = await state.get_data()
    selected_date = user_data.get("date")

    if not selected_date:
        await callback.message.edit_text("Виникла помилка стану (дата). Почніть з /start.")
        await state.clear()
        return

    try:
        # Перевіряємо і бронюємо в одній функції
        booking_successful = update_status(selected_date, selected_time, STATUS_BOOKED)

        if booking_successful:
            await state.update_data(time=selected_time)
            await state.set_state(Form.question)
            await callback.message.edit_text(  # Редагуємо повідомлення
                f"Час {selected_date} {selected_time} успішно заброньовано!\nТепер, будь ласка, опишіть коротко ваше питання або мету консультації:"
            )
        else:
            # Слот вже зайнятий або помилка оновлення
            # Спробуємо оновити клавіатуру часу
            current_available_dates = get_available_dates()
            if selected_date in current_available_dates and current_available_dates[selected_date]:
                keyboard = get_times_keyboard(current_available_dates[selected_date])
                await callback.message.edit_text(
                    f"На жаль, час {selected_time} на {selected_date} щойно зайняли або став недоступним. Спробуйте обрати інший:",
                    reply_markup=keyboard
                )
                await state.set_state(Form.time)  # Залишаємось у стані вибору часу
            else:  # Якщо на цю дату більше взагалі немає часу
                await callback.message.edit_text(
                    f"На жаль, на {selected_date} більше немає вільних слотів. Будь ласка, натисніть 'Назад' або почніть з /start.")
                # Клавіатура часу вже не показується, кнопка Назад має бути з попереднього кроку, але можна додати
                # або просто очистити стан
                await state.set_state(Form.date)  # Повертаємо на вибір дати, бо для поточної немає часу

    except Exception as e:  # Ловимо інші можливі помилки (наприклад, від get_available_dates)
        print(f"Помилка під час спроби забронювати час: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer(
            "Виникла критична помилка при спробі обробити ваш вибір. Будь ласка, почніть з /start.")
        await state.clear()


@dp.message(StateFilter(Form.question))
async def get_question_handler(message: Message, state: FSMContext):
    question = message.text
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {message.from_user.id}")
    selected_date = user_data.get("date")
    selected_time = user_data.get("time")
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    contact_info = telegram_username  # Для гілки консультації контакт беремо з ТГ

    if not selected_date or not selected_time:
        await message.answer("Виникла помилка стану (дата/час). Почніть з /start.")
        await state.clear()
        return

    try:
        # Зберігаємо в Google Sheets
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving appointment for {user_name}...", file=sys.stderr)
        # Порядок стовпців: Ім’я | Контакт | Питання | Telegram ID | Дата | Час | Час Запису
        sheet.append_row([
            user_name, contact_info, question, str(user_id),
            selected_date, selected_time, timestamp
        ])
        print("DEBUG: Appointment saved to Заявки sheet.", file=sys.stderr)

        # --- Надсилання сповіщення адміну ---
        if ADMIN_CHAT_ID:
            notification_text = (
                f"📅 **Новий запис на консультацію!**\n\n"
                f"👤 **Ім'я:** {user_name}\n"
                f"🗓️ **Дата:** {selected_date}\n"
                f"🕒 **Час:** {selected_time}\n"
                f"❓ **Питання:** {question}\n"
                f"💬 **Telegram:** {telegram_username} (ID: {user_id})\n"
                f"⏰ **Час запису:** {timestamp}"
            )
            try:
                await bot.send_message(ADMIN_CHAT_ID, notification_text, parse_mode="MarkdownV2")
                print(f"DEBUG: Sent appointment notification to admin chat {ADMIN_CHAT_ID}", file=sys.stderr)
            except Exception as e_notify:
                print(
                    f"ERROR: Could not send appointment notification to admin {ADMIN_CHAT_ID}: {type(e_notify).__name__} - {e_notify}",
                    file=sys.stderr)
        # ------------------------------------

        # Повідомлення 1: Підтвердження
        await message.answer(
            f"Дякую, {user_name}! Ваш запис на консультацію ({selected_date} {selected_time}) підтверджено!")

        # Повідомлення 2: Деталі (замініть плейсхолдери!)
        lawyer_contact_for_booking_questions = "ВАШ_ТЕЛЕФОН_АБО_EMAIL_ДЛЯ_ЗАПИТАНЬ"  # ЗАМІНІТЬ
        payment_details_text = 'Реквізити для оплати будуть надіслані вам додатково. Оплату необхідно здійснити до початку консультації.'  # ЗАМІНІТЬ/УТОЧНІТЬ

        details_text_html = (
            f"🗓️ <b>Деталі вашого запису:</b> {selected_date} о {selected_time}.\n\n"
            f"<b>Порядок проведення онлайн-консультації:</b>\n\n"
            f"1️⃣ <b>Платформа:</b> Ми зв'яжемося з вами незадовго до початку за контактом (<code>{contact_info}</code>), щоб узгодити зручну платформу (Zoom, Google Meet, Teams, Viber, WhatsApp, Telegram тощо) та надати посилання.\n\n"
            f"2️⃣ <b>Підготовка:</b> Якщо ваше питання стосується документів, підготуйте їх копії/фото. Будь ласка, забезпечте стабільний інтернет та тихе місце.\n\n"
            f"3️⃣ <b>Оплата:</b> Вартість - <b>1000 грн/год</b>. {payment_details_text}\n\n"
            f"4️⃣ <b>Консультація:</b> Будьте готові обговорити ваше питання. Адвокат Меркович Богдан надасть вам необхідні роз'яснення та рекомендації.\n\n"
            f"5️⃣ <b>Зв'язок:</b> З термінових питань щодо запису <i>до</i> консультації звертайтесь: {lawyer_contact_for_booking_questions}.\n\n"
            f"Очікуйте на зв'язок для узгодження платформи!"
        )
        await message.answer(details_text_html, parse_mode="HTML")

        # Повертаємось на старт, передаючи ім'я
        await cmd_start(message, state, remembered_name=user_name)

    except Exception as e:
        print(f"Помилка збереження запису консультації: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("На жаль, сталася помилка під час фінального збереження вашого запису...")
        # Очищуємо стан у разі помилки
        await state.clear()

# --- Код для запуску через Uvicorn/FastAPI (у файлі main.py) ---
# Цей файл bot.py не повинен містити блоків if __name__ == '__main__': або dp.start_polling()
# Його об'єкти bot та dp імпортуються у main.py