# /root/telegram-schedule-bot/bot/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from datetime import datetime
from typing import List, Dict, Any # Для тайп хінтів

# Импортируем формат даты из google_sheets.py, где он определен
from .google_sheets import DATE_FORMAT_IN_SHEET

MESSENGER_OPTIONS = {
    "viber": "Viber",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "zoom": "Zoom",
    "teams": "Teams"
}

def get_messenger_choice_keyboard() -> InlineKeyboardMarkup:
    """Створює inline-клавіатуру для вибору месенджера."""
    builder = InlineKeyboardBuilder()
    for callback_data_key, text in MESSENGER_OPTIONS.items():
        builder.button(text=text, callback_data=f"messenger_{callback_data_key}")
    builder.adjust(2) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_booking_phone")) # Кнопка назад до введення номера
    return builder.as_markup()

def get_service_choice_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру для начального выбора услуги."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Залишити контакт", callback_data="ask_contact")
    builder.button(text="📅 Записатися на консультацію", callback_data="book_consultation")
    builder.button(text="❌ Скасувати мій запис", callback_data="cancel_my_booking_start") # Нова кнопка
    builder.adjust(1) # Кожна кнопка в новому рядку для кращої читабельності
    return builder.as_markup()

def get_dates_keyboard(dates_dict: dict) -> InlineKeyboardMarkup:
    """
    Создает inline-клавиатуру с доступными датами и кнопкой 'Назад'.
    dates_dict: Словарь { 'дата_строка': ['время1', 'время2'], ... }
    """
    builder = InlineKeyboardBuilder()
    try:
        sorted_dates = sorted(
            dates_dict.keys(),
            key=lambda d_str: datetime.strptime(d_str.strip(), DATE_FORMAT_IN_SHEET).date()
        )
    except Exception as e_sort:
        import sys
        print(f"ОШИБКА [keyboards.py]: Ошибка сортировки дат: {e_sort}. Используются несортированные ключи.", file=sys.stderr)
        sorted_dates = list(dates_dict.keys())

    for date_str in sorted_dates:
        builder.button(text=date_str, callback_data=f"date_{date_str}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service_choice_from_date"))
    return builder.as_markup()

def get_times_keyboard(times_list: list) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с доступным временем и кнопкой 'Назад'."""
    builder = InlineKeyboardBuilder()
    for time_str in sorted(times_list): # Сортуємо час для консистентності
        builder.button(text=time_str, callback_data=f"time_{time_str}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date_selection"))
    return builder.as_markup()

def get_share_contact_keyboard() -> ReplyKeyboardMarkup:
    """Создает reply-клавиатуру для запроса номера телефона пользователя."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Поділитися моїм номером телефону", request_contact=True)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Створює inline-клавіатуру з кнопкою 'Повернутися на головне меню'."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Повернутися на головне меню", callback_data="main_menu_start")
    return builder.as_markup()


def get_user_bookings_keyboard(bookings: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Створює inline-клавіатуру зі списком бронювань користувача для скасування.
    bookings: Список словників, кожен з яких містить 'date', 'time', 'row_index'.
    """
    builder = InlineKeyboardBuilder()
    if not bookings:
        # Теоретично, ця клавіатура не повинна викликатися з порожнім списком,
        # але для безпеки можна додати кнопку "На головне меню"
        builder.button(text="🤷 Записів не знайдено. На головне меню", callback_data="main_menu_start")
        return builder.as_markup()

    for booking in bookings:
        # callback_data буде містити row_index, date, time через розділювач, наприклад '_'
        # Це потрібно, щоб потім отримати ці дані в хендлері
        # Важливо: row_index - це індекс рядка в Google Sheet "Заявки"
        # date і time потрібні для оновлення статусу в аркуші "Графік"
        callback_info = f"{booking['row_index']}_{booking['date']}_{booking['time']}"
        display_text = f"Скасувати: {booking['date']} о {booking['time']}"
        if booking.get('question'): # Додамо частину питання для кращої ідентифікації
            display_text += f" ({booking['question'][:20]}...)" if len(booking['question']) > 20 else f" ({booking['question']})"
        builder.button(text=display_text, callback_data=f"cancel_selected_booking_{callback_info}")
    
    builder.adjust(1) # Кожне бронювання на окремій кнопці
    builder.row(InlineKeyboardButton(text="⬅️ На головне меню", callback_data="main_menu_start"))
    return builder.as_markup()


def get_confirm_cancellation_keyboard(booking_callback_info: str) -> InlineKeyboardMarkup:
    """
    Створює inline-клавіатуру для підтвердження скасування.
    booking_callback_info: Рядок з даними про бронювання (row_index_date_time).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, скасувати запис", callback_data=f"confirm_cancellation_yes_{booking_callback_info}")
    builder.button(text="❌ Ні, залишити запис", callback_data="confirm_cancellation_no") # Можна повернути до списку записів або на головне меню
    builder.adjust(1)
    return builder.as_markup()
