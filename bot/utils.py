# /root/telegram-schedule-bot/bot/utils.py
# Этот файл содержит вспомогательные функции, такие как отправка уведомлений админу.
# Логика Google Sheets остается в google_sheets.py

import sys
from aiogram import Bot

# ADMIN_CHAT_ID будет импортирован из bot.bot в тех модулях, где он нужен (например, handlers.py)
# bot_instance также будет передаваться в функции оттуда.

from typing import Optional
import sys

async def send_admin_notification(bot_instance: 'Bot', admin_chat_id: Optional[int], html_text: str) -> None:
    """Отправляет HTML-форматированное уведомление админу."""
    if admin_chat_id is None:
        print("DEBUG [utils.py]: Уведомления админу отключены (ADMIN_CHAT_ID не установлен).", file=sys.stderr)
        return

    try:
        await bot_instance.send_message(admin_chat_id, html_text, parse_mode="HTML")
        print(f"DEBUG [utils.py]: Отправлено уведомление в админ-чат {admin_chat_id}", file=sys.stderr)
    except Exception as e_notify:
        print(
            f"ОШИБКА [utils.py]: Не удалось отправить уведомление админу {admin_chat_id}: {type(e_notify).__name__} - {e_notify}",
            file=sys.stderr
        )

def _escape_html(text: Optional[str]) -> str:
    """Простое экранирование HTML для безопасной вставки в сообщения."""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def notify_admin_new_contact(
    bot_instance: 'Bot',
    admin_chat_id: Optional[int],
    user_name: str,
    contact_info: str,
    telegram_username: str,
    user_id: int,
    timestamp: str,
    contact_type: str
) -> None:
    """Формирует и отправляет уведомление о новом контакте."""
    text = (
        f"🔔 <b>Новий запит на дзвінок ({_escape_html(contact_type)})</b>\n\n"
        f"👤 <b>Ім'я:</b> {_escape_html(user_name)}\n"
        f"📞 <b>Контакт:</b> <code>{_escape_html(contact_info)}</code>\n"
        f"💬 <b>Telegram:</b> {_escape_html(telegram_username)} (ID: <code>{user_id}</code>)\n"
        f"⏰ <b>Час запиту:</b> {_escape_html(timestamp)}"
    )
    await send_admin_notification(bot_instance, admin_chat_id, text)

async def notify_admin_new_booking(
    bot_instance: 'Bot',
    admin_chat_id: Optional[int],
    user_name: str,
    selected_date: str,
    selected_time: str,
    question: str,
    telegram_username: str,
    user_id: int,
    timestamp: str
) -> None:
    """Формирует и отправляет уведомление о новом бронировании."""
    text = (
        f"📅 <b>Новий запис на консультацію!</b>\n\n"
        f"👤 <b>Ім'я:</b> {_escape_html(user_name)}\n"
        f"🗓️ <b>Дата:</b> {_escape_html(selected_date)}\n"
        f"🕒 <b>Час:</b> {_escape_html(selected_time)}\n"
        f"❓ <b>Питання:</b> {_escape_html(question)}\n"
        f"💬 <b>Telegram:</b> {_escape_html(telegram_username)} (ID: <code>{user_id}</code>)\n"
        f"⏰ <b>Час запису:</b> {_escape_html(timestamp)}"
    )
    await send_admin_notification(bot_instance, admin_chat_id, text)

# Другие общие вспомогательные функции, не связанные напрямую с Google Sheets или хендлерами,
# можно добавить сюда.
