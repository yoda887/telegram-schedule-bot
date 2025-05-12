# /root/telegram-schedule-bot/bot/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from datetime import datetime

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
    builder.adjust(2) # Розміщуємо по 2 кнопки в ряд
    # Тут можна додати кнопку "Назад", якщо потрібно повернутися до введення номера телефону
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_booking_phone"))
    return builder.as_markup()

def get_service_choice_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру для начального выбора услуги."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Залишити контакт", callback_data="ask_contact")
    builder.button(text="📅 Записатися на консультацію", callback_data="book_consultation")
    builder.adjust(1)
    return builder.as_markup()

def get_dates_keyboard(dates_dict: dict) -> InlineKeyboardMarkup:
    """
    Создает inline-клавиатуру с доступными датами и кнопкой 'Назад'.
    dates_dict: Словарь { 'дата_строка': ['время1', 'время2'], ... }
    """
    builder = InlineKeyboardBuilder()
    try:
        # Используем DATE_FORMAT_IN_SHEET, импортированный из google_sheets
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
    for time_str in sorted(times_list):
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