# /root/telegram-schedule-bot/bot/bot.py

import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import sys

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from .google_sheets import (
    get_available_dates, update_status, get_gspread_client,
    SPREADSHEET_NAME, REQUESTS_WORKSHEET_NAME, SCHEDULE_WORKSHEET_NAME,
    STATUS_BOOKED, STATUS_FREE, DATE_FORMAT_IN_SHEET  # Імпортуємо константи
)
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
    callback_name = State()
    booking_name = State()
    service_choice = State()
    phone_number = State()
    date = State()
    time = State()
    question = State()


# --- Клавіатури ---
def get_service_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Залишити контакт", callback_data="ask_contact")
    builder.button(text="📅 Записатися на консультацію", callback_data="book_consultation")
    builder.adjust(1)
    return builder.as_markup()


def get_dates_keyboard(dates_dict):
    builder = InlineKeyboardBuilder()
    # Сортуємо дати перед відображенням
    try:
        # Переконуємось, що DATE_FORMAT_IN_SHEET глобально доступний або переданий
        sorted_dates = sorted(dates_dict.keys(),
                              key=lambda d_str: datetime.strptime(d_str, DATE_FORMAT_IN_SHEET).date())
    except Exception as e_sort:
        print(f"Error sorting dates in get_dates_keyboard: {e_sort}. Using unsorted keys.", file=sys.stderr)
        sorted_dates = list(dates_dict.keys())  # Fallback to unsorted

    for date_str in sorted_dates:
        builder.button(text=date_str, callback_data=f"date_{date_str}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service_choice_from_date"))
    return builder.as_markup()


def get_times_keyboard(times_list):
    builder = InlineKeyboardBuilder()
    # Сортуємо час (якщо він у форматі HH:MM, рядкове сортування спрацює)
    for time_str in sorted(times_list):
        builder.button(text=time_str, callback_data=f"time_{time_str}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date_selection"))
    return builder.as_markup()


def get_share_contact_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Поділитися моїм номером телефону", request_contact=True)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# --- Обробники ---
async def show_service_choice_menu(target_message_or_callback: types.TelegramObject, state: FSMContext,
                                   user_name: str = None):
    """Показує меню вибору послуг, редагуючи повідомлення або надсилаючи нове."""
    await state.set_state(Form.service_choice)
    keyboard = get_service_choice_keyboard()
    text = f"Привіт, {user_name}! 👋\nЯк я можу допомогти?" if user_name else "Привіт! 👋\nЯк я можу допомогти?"

    if isinstance(target_message_or_callback, CallbackQuery):
        try:
            await target_message_or_callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            # Якщо редагування не вдалося (напр., текст той самий), надсилаємо нове для показу кнопок
            await target_message_or_callback.message.answer(text, reply_markup=keyboard)
    elif isinstance(target_message_or_callback, Message):
        await target_message_or_callback.answer(text, reply_markup=keyboard)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # Одразу показуємо кнопки вибору послуги
    await show_service_choice_menu(message, state)


@dp.callback_query(StateFilter(Form.service_choice))
async def service_choice_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    choice_data = callback.data

    # Прибираємо кнопки з попереднього повідомлення
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e_edit_markup:
        print(f"Could not edit reply markup: {e_edit_markup}", file=sys.stderr)

    if choice_data == "ask_contact":
        await state.set_state(Form.callback_name)
        await callback.message.answer("Добре, я запишу ваші контакти.\nБудь ласка, напишіть ваше ім'я:")
    elif choice_data == "book_consultation":
        await state.set_state(Form.booking_name)
        await callback.message.answer("Добре, запишемо вас на консультацію.\nБудь ласка, напишіть ваше ім'я:")
    else:
        await callback.message.answer("Невідома опція. Почніть з /start.")
        await state.clear()  # Очищуємо стан, якщо опція невідома


@dp.message(StateFilter(Form.callback_name))
async def callback_name_handler(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Form.phone_number)
    keyboard = get_share_contact_keyboard()
    await message.answer(
        "Дякую! Тепер, будь ласка, поділіться вашим номером телефону, натиснувши кнопку нижче, "
        "або введіть ваш контакт (телефон або інший спосіб зв'язку) вручну:",
        reply_markup=keyboard
    )


@dp.message(StateFilter(Form.booking_name))
async def booking_name_handler(message: Message, state: FSMContext):
    user_name = message.text
    await state.update_data(name=user_name)
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


@dp.message(StateFilter(Form.phone_number), F.contact)
async def contact_shared_handler(message: Message, state: FSMContext):
    contact_info = message.contact.phone_number
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")

    await state.update_data(contact=contact_info)

    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving SHARED contact for {user_name} - {contact_info}...", file=sys.stderr)
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт пошарено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG: SHARED contact info saved.", file=sys.stderr)
        await message.answer(
            f"Дякую, {user_name}! Ваш номер телефону: {contact_info} отримано.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await cmd_start(message, state)
    except Exception as e:
        print(f"Помилка збереження SHARED контакту: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer(
            "Виникла помилка під час збереження ваших даних...",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.clear()


@dp.message(StateFilter(Form.phone_number), F.text)
async def get_phone_number_text_handler(message: Message, state: FSMContext):
    contact_info = message.text
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")

    await state.update_data(contact=contact_info)  # Зберігаємо введений контакт

    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving TYPED contact for {user_name} - {contact_info}...", file=sys.stderr)
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт введено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG: TYPED contact info saved.", file=sys.stderr)
        await message.answer(
            f"Дякую, {user_name}! Ваші контактні дані: '{contact_info}' отримані. Я зв'яжуся з вами.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await cmd_start(message, state)
    except Exception as e:
        print(f"Помилка збереження TYPED контакту: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer(
            "Виникла помилка під час збереження ваших даних...",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.clear()


# --- Обробники для кнопок "Назад" ---
@dp.callback_query(F.data == "back_to_service_choice_from_date", StateFilter(Form.date))
async def back_to_service_choice_from_date_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")
    await show_service_choice_menu(callback, state, user_name)


@dp.callback_query(F.data == "back_to_date_selection", StateFilter(Form.time))
async def back_to_date_selection_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")  # Ім'я вже має бути в стані
    try:
        available_dates = get_available_dates()
        if not available_dates:
            await callback.message.edit_text("На жаль, на даний момент немає доступних дат. Повертаю на головне меню.")
            await show_service_choice_menu(callback, state, user_name)
            return

        keyboard = get_dates_keyboard(available_dates)
        await callback.message.edit_text(
            f"{user_name}, ось доступні дати для запису:\n(дійсні на найближчі 7 днів)\nВиберіть дату:",
            reply_markup=keyboard
        )
        await state.set_state(Form.date)
    except Exception as e:
        print(f"Помилка в back_to_date_selection_handler: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.edit_text("Виникла помилка. Повертаю на головне меню.")
        await show_service_choice_menu(callback, state, user_name)


@dp.callback_query(StateFilter(Form.date), F.data.startswith("date_"))
async def get_date_callback_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    selected_date = callback.data.split("date_")[1]
    try:
        available_dates = get_available_dates()
        if selected_date in available_dates and available_dates[selected_date]:
            available_times = available_dates[selected_date]
            await state.update_data(date=selected_date)
            await state.set_state(Form.time)
            keyboard = get_times_keyboard(available_times)
            await callback.message.edit_text(
                f"Доступні часи на {selected_date}:\nВиберіть час:",
                reply_markup=keyboard
            )
        else:
            keyboard = get_dates_keyboard(available_dates)  # Оновлюємо, бо дані могли змінитися
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
        booking_successful = update_status(selected_date, selected_time, STATUS_BOOKED)
        if booking_successful:
            await state.update_data(time=selected_time)
            await state.set_state(Form.question)
            await callback.message.edit_text(
                f"Час {selected_date} {selected_time} успішно заброньовано!\nТепер, будь ласка, опишіть коротко ваше питання або мету консультації:"
            )
        else:
            current_available_dates = get_available_dates()
            if selected_date in current_available_dates and current_available_dates[selected_date]:
                keyboard = get_times_keyboard(current_available_dates[selected_date])
                await callback.message.edit_text(
                    f"На жаль, час {selected_time} на {selected_date} щойно зайняли або став недоступним. Спробуйте обрати інший:",
                    reply_markup=keyboard
                )
                # Залишаємось у стані вибору часу для тієї ж дати
                await state.set_state(Form.time)
            else:  # Якщо на цю дату більше взагалі немає часу
                await callback.message.edit_text(
                    f"На жаль, на {selected_date} більше немає вільних слотів. Будь ласка, почніть з /start, щоб побачити актуальний графік.")
                await state.clear()
    except Exception as e:
        print(f"Помилка під час спроби забронювати час: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer("Виникла критична помилка. Почніть з /start.")
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
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print(f"DEBUG: Saving appointment for {user_name}...", file=sys.stderr)
        sheet.append_row([
            user_name, contact_info, question, str(user_id),
            selected_date, selected_time, timestamp
        ])
        print("DEBUG: Appointment saved to Заявки sheet.", file=sys.stderr)
        await message.answer(
            f"Дякую, {user_name}! Ваш запис на консультацію ({selected_date} {selected_time}) підтверджено!")

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
        await cmd_start(message, state)  # Повернення на старт
    except Exception as e:
        print(f"Помилка збереження запису консультації в Google Sheets: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("На жаль, сталася помилка під час фінального збереження вашого запису...")
        await state.clear()

# Блок запуску polling НЕ потрібен, оскільки FastAPI/Uvicorn керує циклом подій.
# async def main_polling():
# await dp.start_polling(bot)
# if __name__ == '__main__':
# import logging
# logging.basicConfig(level=logging.INFO, stream=sys.stdout)
# asyncio.run(main_polling())