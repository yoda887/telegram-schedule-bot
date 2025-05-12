# /root/telegram-schedule-bot/bot/handlers.py
# Этот файл содержит все обработчики (хендлеры) для команд, сообщений и коллбеков.
# Используем Aiogram Router для лучшей организации.

import os
import sys
from datetime import datetime
import pytz # <<< ДОДАЙТЕ ЦЕЙ ІМПОРТ

from aiogram import Router, types, F
from aiogram.filters import CommandStart, StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove

# Импортируем основные объекты бота, состояния, клавиатуры и утилиты
from .bot import bot, ADMIN_CHAT_ID  # Из нашего bot.py
from .states import Form
from .keyboards import (
    get_service_choice_keyboard,
    get_dates_keyboard,
    get_times_keyboard,
    get_share_contact_keyboard,
    get_back_to_main_menu_keyboard,
    get_messenger_choice_keyboard, # <<< НАШ НОВИЙ ІМПОРТ
    MESSENGER_OPTIONS # <<< ІМПОРТУЄМО ОПЦІЇ МЕСЕНДЖЕРІВ
)
# Импортируем функции для работы с Google Sheets
from .google_sheets import (
    get_available_dates,
    update_status,
    get_client_provided_name,
    save_or_update_client_name,
    get_gspread_client,  # Нужен для прямого вызова в хендлерах
    SPREADSHEET_NAME,  # Нужны для прямого вызова
    REQUESTS_WORKSHEET_NAME,
    STATUS_BOOKED,
    KYIV_TZ,
    # DATE_FORMAT_IN_SHEET # Уже импортирован в keyboards.py

)
# Импортируем утилиты для уведомлений
from .utils import notify_admin_new_contact, notify_admin_new_booking, notify_admin_new_booking_extended

# Якщо KYIV_TZ не імпортується, визначте його тут:
if 'KYIV_TZ' not in globals():
    KYIV_TZ = pytz.timezone('Europe/Kiev')

# Создаем главный роутер для всех хендлеров
main_router = Router(name="main_handlers_router")


# --- Вспомогательная функция для отображения меню выбора услуг ---
async def show_service_choice_menu(target_message_or_callback: types.TelegramObject, state: FSMContext,
                                   user_name: str = None):
    """Отображает меню выбора услуг, редактируя сообщение или отправляя новое."""
    await state.set_state(Form.service_choice)
    keyboard = get_service_choice_keyboard()
    greeting = f"Привіт, {user_name}! 👋\n" if user_name else "Привіт! 👋\n"
    text = f"{greeting}Як я можу допомогти?"

    if isinstance(target_message_or_callback, CallbackQuery):
        try:
            await target_message_or_callback.message.edit_text(text, reply_markup=keyboard)
        except Exception as e_edit:
            print(f"DEBUG [handlers.py]: Не удалось отредактировать сообщение, отправляю новое. Ошибка: {e_edit}",
                  file=sys.stderr)
            await target_message_or_callback.message.answer(text, reply_markup=keyboard)
    elif isinstance(target_message_or_callback, Message):
        await target_message_or_callback.answer(text, reply_markup=keyboard)


# --- Обработчики ---

@main_router.message(CommandStart())
async def cmd_start_handler(message: Message, state: FSMContext, remembered_name: str = None):
    """Обрабатывает команду /start."""
    await state.clear()
    user_id = message.from_user.id
    stored_name = None

    if not remembered_name:
        try:
            stored_name = get_client_provided_name(user_id)
        except Exception as e:
            print(f"ОШИБКА [handlers.py]: проверка сохраненного имени клиента: {type(e).__name__} - {e}",
                  file=sys.stderr)

    display_name = remembered_name or stored_name
    if display_name:
        await state.update_data(name=display_name)

    await show_service_choice_menu(message, state, display_name)


@main_router.message(Command("rename"))
async def cmd_rename_handler(message: Message, state: FSMContext):
    """Обробляє команду /rename для зміни збереженого імені користувача."""
    await state.clear()  # Спочатку очистимо будь-який попередній стан
    user_id = message.from_user.id

    # Спробуємо отримати поточне ім'я спочатку з FSM, потім з Google Sheets
    user_fsm_data = await state.get_data()
    current_name = user_fsm_data.get("name")

    if not current_name:
        try:
            current_name_from_sheet = get_client_provided_name(user_id)
            if current_name_from_sheet:
                current_name = current_name_from_sheet
        except Exception as e:
            print(f"DEBUG [handlers.py]: Помилка отримання імені для /rename user {user_id}: {e}", file=sys.stderr)

    if current_name:
        await state.update_data(
            current_name_for_rename=current_name)  # Збережемо поточне ім'я на випадок, якщо знадобиться
        await message.answer(
            f"Ваше поточне збережене ім'я: <b>{current_name}</b>.\n"
            "Будь ласка, введіть нове ім'я:",
            parse_mode="HTML"
        )
        await state.set_state(Form.renaming_name)
    else:
        await message.answer(
            "Здається, для вас ще не збережено ім'я. Ви можете встановити його, "
            "скориставшись функцією запису на консультацію або залишення контакту."
        )
        await message.answer(
            "Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )


@main_router.message(StateFilter(Form.renaming_name), F.text)
async def process_new_name_handler(message: Message, state: FSMContext):
    """Обробляє нове ім'я, введене користувачем."""
    new_name = message.text.strip()
    user_id = message.from_user.id
    tg_username = f"@{message.from_user.username}" if message.from_user.username else ""

    if not new_name:  # Проста валідація
        await message.answer("Ім'я не може бути порожнім. Будь ласка, введіть коректне ім'я:")
        return  # Залишаємося в стані Form.renaming_name

    try:
        save_or_update_client_name(user_id, tg_username, new_name)  # Зберігаємо/оновлюємо в Google Sheets
        await state.update_data(name=new_name)  # Оновлюємо ім'я в поточному стані FSM

        await message.answer(
            f"Ваше ім'я успішно змінено на: <b>{new_name}</b>.",
            parse_mode="HTML"
        )
        print(f"DEBUG [handlers.py]: Ім'я для user {user_id} оновлено на '{new_name}' через /rename.", file=sys.stderr)

        # Пропонуємо повернутися до головного меню
        await message.answer(
            "Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear()  # Очищуємо стан після успішної зміни

    except Exception as e:
        print(
            f"ОШИБКА [handlers.py]: під час оновлення імені для user {user_id} через /rename: {type(e).__name__} - {e}",
            file=sys.stderr)
        await message.answer("На жаль, сталася помилка під час оновлення вашого імені. Спробуйте пізніше.")
        await message.answer(
            "Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear()


@main_router.message(StateFilter(Form.renaming_name)) # Обробник для нетекстового вводу
async def process_new_name_invalid_input_handler(message: Message, state: FSMContext):
    """Обробляє нетекстовий ввід, коли очікується нове ім'я."""
    await message.answer("Будь ласка, введіть ваше нове ім'я текстом. Якщо бажаєте скасувати зміну імені, можете скористатися командою /start.")


@main_router.callback_query(StateFilter(Form.service_choice))
async def service_choice_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє вибір послуги, перевіряючи, чи відоме ім'я користувача."""
    await callback.answer()
    choice_data = callback.data

    user_id = callback.from_user.id
    user_fsm_data = await state.get_data()
    user_name = user_fsm_data.get("name")

    if not user_name:  # Якщо імені немає в стані FSM
        try:
            print(
                f"DEBUG [handlers.py]: Ім'я не знайдено в FSM для user {user_id}. Запит до get_client_provided_name...",
                file=sys.stderr)
            user_name_from_sheet = get_client_provided_name(user_id)  # Функція з google_sheets.py
            if user_name_from_sheet:
                user_name = user_name_from_sheet
                await state.update_data(name=user_name)  # Зберігаємо знайдене ім'я в FSM
                print(f"DEBUG [handlers.py]: Ім'я '{user_name}' знайдено для user {user_id} та збережено в FSM.",
                      file=sys.stderr)
            else:
                print(f"DEBUG [handlers.py]: Ім'я для user {user_id} не знайдено ні в FSM, ні в Sheets.",
                      file=sys.stderr)
        except Exception as e:
            print(f"ОШИБКА [handlers.py]: при отриманні імені для user {user_id} в service_choice: {e}",
                  file=sys.stderr)

    # Спробуємо прибрати клавіатуру попереднього вибору
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e_edit_markup:
        print(f"DEBUG [handlers.py]: Не вдалося відредагувати клавіатуру в service_choice: {e_edit_markup}",
              file=sys.stderr)

    if choice_data == "ask_contact":
        if user_name:  # Якщо ім'я відоме
            await state.set_state(Form.phone_number)
            keyboard = get_share_contact_keyboard()
            # Редагуємо попереднє повідомлення або надсилаємо нове
            await callback.message.answer(  # Надсилаємо нове, бо edit_reply_markup вже було
                f"Дякую, {user_name}! Тепер, будь ласка, поділіться вашим номером телефону, натиснувши кнопку нижче, "
                "або введіть ваш контакт (телефон або інший спосіб зв'язку) вручну:",
                reply_markup=keyboard
            )
        else:  # Якщо ім'я невідоме
            await state.set_state(Form.callback_name)
            await callback.message.answer("Добре, я запишу ваші контакти.\nБудь ласка, напишіть ваше ім'я:")

    elif choice_data == "book_consultation":
        if user_name:  # Якщо ім'я відоме
            # Переходимо до вибору дати, викликаючи нову допоміжну функцію
            # Вона оновить повідомлення callback.message
            await show_available_dates_for_booking(callback, state, user_name)
        else:  # Якщо ім'я невідоме
            await state.set_state(Form.booking_name)
            await callback.message.answer("Добре, запишемо вас на консультацію.\nБудь ласка, напишіть ваше ім'я:")

    else:
        await callback.message.answer("Невідома опція. Будь ласка, почніть з /start.")
        await state.clear()


@main_router.message(StateFilter(Form.callback_name))
async def callback_name_handler(message: Message, state: FSMContext):
    """Отримує ім'я для зворотного дзвінка, зберігає його і запитує телефон."""
    user_name_provided = message.text
    await state.update_data(name=user_name_provided)
    user_id = message.from_user.id
    tg_username = f"@{message.from_user.username}" if message.from_user.username else ""

    try:
        save_or_update_client_name(user_id, tg_username, user_name_provided)
        print(
            f"DEBUG [handlers.py]: Ім'я '{user_name_provided}' збережено/оновлено для user {user_id} (зворотний дзвінок).",
            file=sys.stderr)
    except Exception as e:
        print(f"ОШИБКА [handlers.py]: збереження імені клієнта (гілка контакту): {type(e).__name__} - {e}",
              file=sys.stderr)

    await state.set_state(Form.phone_number)
    keyboard = get_share_contact_keyboard()
    await message.answer(
        f"Дякую, {user_name_provided}! Тепер, будь ласка, поділіться вашим номером телефону, натиснувши кнопку нижче, "
        "або введіть ваш контакт (телефон або інший спосіб зв'язку) вручну:",
        reply_markup=keyboard
    )


# /root/telegram-schedule-bot/bot/handlers.py

@main_router.message(StateFilter(Form.phone_number), F.contact)
async def contact_shared_handler(message: Message, state: FSMContext):
    """Обробляє контакт, яким користувач поділився через кнопку."""
    contact_info = message.contact.phone_number
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")
    await state.update_data(contact=contact_info)

    try:
        timestamp = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S") # Використовуємо KYIV_TZ, якщо налаштовано
        g_client = get_gspread_client()
        sheet = g_client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        print(f"DEBUG [handlers.py]: Сохранение SHARED контакта для {user_name}...", file=sys.stderr)
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт пошарено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG [handlers.py]: SHARED контакт сохранен.", file=sys.stderr)

        await notify_admin_new_contact(bot, ADMIN_CHAT_ID, user_name, contact_info, telegram_username, user_id,
                                       timestamp, "Контакт пошарено")

        await message.answer(
            f"Дякую, {user_name}! Ваш номер телефону: {contact_info} отримано.",
            reply_markup=ReplyKeyboardRemove()
        )
        # ЗАМІСТЬ: await cmd_start_handler(message, state, remembered_name=user_name)
        # НАДІСЛАТИ КНОПКУ:
        await message.answer(
            "Ваш запит на дзвінок прийнято. Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear() # Очищуємо стан після завершення

    except Exception as e:
        print(f"ОШИБКА [handlers.py]: сохранения SHARED контакта: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("Виникла помилка під час збереження ваших даних...", reply_markup=ReplyKeyboardRemove())
        await state.clear()


# /root/telegram-schedule-bot/bot/handlers.py

@main_router.message(StateFilter(Form.phone_number), F.text)
async def get_phone_number_text_handler(message: Message, state: FSMContext):
    """Обрабатывает контакт, введенный пользователем вручную."""
    contact_info = message.text
    user_id = message.from_user.id
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {user_id}")
    await state.update_data(contact=contact_info)

    try:
        g_client = get_gspread_client()
        sheet = g_client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        timestamp = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S") # Використовуємо KYIV_TZ, якщо налаштовано
        print(f"DEBUG [handlers.py]: Сохранение TYPED контакта для {user_name}...", file=sys.stderr)
        sheet.append_row([
            user_name, contact_info, "Запит на дзвінок (контакт введено)",
            telegram_username, "", "", timestamp
        ])
        print("DEBUG [handlers.py]: TYPED контакт сохранен.", file=sys.stderr)

        await notify_admin_new_contact(bot, ADMIN_CHAT_ID, user_name, contact_info, telegram_username, user_id,
                                       timestamp, "Контакт введено")

        await message.answer(
            f"Дякую, {user_name}! Ваші контактні дані: '{contact_info}' отримані. Я зв'яжуся з вами.",
            reply_markup=ReplyKeyboardRemove()
        )
        # ЗАМІСТЬ: await cmd_start_handler(message, state, remembered_name=user_name)
        # НАДІСЛАТИ КНОПКУ:
        await message.answer(
            "Ваш запит на дзвінок прийнято. Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear() # Очищуємо стан після завершення

    except Exception as e:
        print(f"ОШИБКА [handlers.py]: сохранения TYPED контакта: {type(e).__name__} - {e}", file=sys.stderr)
        await message.answer("Виникла помилка під час збереження ваших даних...", reply_markup=ReplyKeyboardRemove())
        await state.clear()


# --- Ветка "Записаться на консультацию" ---
# /root/telegram-schedule-bot/bot/handlers.py

@main_router.message(StateFilter(Form.booking_name))
async def booking_name_handler(message: Message, state: FSMContext):
    """Отримує ім'я для бронювання, зберігає його і показує доступні дати."""
    user_name_provided = message.text
    await state.update_data(name=user_name_provided)
    user_id = message.from_user.id
    # tg_username може бути None, save_or_update_client_name має це обробляти
    tg_username = f"@{message.from_user.username}" if message.from_user.username else ""

    try:
        save_or_update_client_name(user_id, tg_username, user_name_provided)
        print(f"DEBUG [handlers.py]: Ім'я '{user_name_provided}' збережено/оновлено для user {user_id}.",
              file=sys.stderr)
    except Exception as e:
        print(f"ОШИБКА [handlers.py]: збереження імені клієнта (гілка бронювання): {type(e).__name__} - {e}",
              file=sys.stderr)

    # Тепер викликаємо допоміжну функцію
    await show_available_dates_for_booking(message, state, user_name_provided)





# --- Обработчики кнопок "Назад" ---
@main_router.callback_query(F.data == "back_to_service_choice_from_date", StateFilter(Form.date))
async def back_to_service_choice_from_date_handler(callback: CallbackQuery, state: FSMContext):
    """Возвращает пользователя к выбору услуги из меню выбора даты."""
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")
    await show_service_choice_menu(callback, state, user_name)


@main_router.callback_query(F.data == "back_to_date_selection", StateFilter(Form.time))
async def back_to_date_selection_handler(callback: CallbackQuery, state: FSMContext):
    """Возвращает пользователя к выбору даты из меню выбора времени."""
    await callback.answer()
    user_data = await state.get_data()
    user_name = user_data.get("name")
    try:
        available_dates = get_available_dates()
        if not available_dates:
            await callback.message.edit_text("На жаль, на даний момент немає доступних дат. Повертаю на головне меню.")
            await show_service_choice_menu(callback, state, user_name)
            return
        keyboard = get_dates_keyboard(available_dates)  # DATE_FORMAT_IN_SHEET используется внутри get_dates_keyboard
        await callback.message.edit_text(
            f"{user_name}, ось доступні дати для запису (на 7 днів):\nВиберіть дату:",
            reply_markup=keyboard
        )
        await state.set_state(Form.date)
    except Exception as e:
        print(f"ОШИБКА [handlers.py]: в back_to_date_selection: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.edit_text("Виникла помилка. Повертаю на головне меню.")
        await show_service_choice_menu(callback, state, user_name)


# --- Обработчики выбора даты, времени, вопроса ---
@main_router.callback_query(StateFilter(Form.date), F.data.startswith("date_"))
async def get_date_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор даты пользователем."""
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
            keyboard = get_dates_keyboard(
                available_dates)  # DATE_FORMAT_IN_SHEET используется внутри get_dates_keyboard
            await callback.message.edit_text(
                "На жаль, ця дата або час на неї вже недоступні. Спробуйте вибрати іншу або натисніть 'Назад'.",
                reply_markup=keyboard
            )
            await state.set_state(Form.date)
    except Exception as e:
        print(f"ОШИБКА [handlers.py]: получения/проверки даты (callback): {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer("Виникла помилка. Будь ласка, почніть з /start.")
        await state.clear()


@main_router.callback_query(StateFilter(Form.time), F.data.startswith("time_"))
async def get_time_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор времени пользователем."""
    await callback.answer()
    selected_time = callback.data.split("time_")[1]
    user_data = await state.get_data()
    selected_date = user_data.get("date")
    user_name = user_data.get("name", f"User {callback.from_user.id}")

    if not selected_date:
        await callback.message.edit_text(
            "Виникла помилка стану (не знайдено обрану дату). Будь ласка, почніть з /start.")
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
                await state.set_state(Form.time)
            else:
                await callback.message.edit_text(
                    f"На жаль, на {selected_date} більше немає вільних слотів. Будь ласка, натисніть 'Назад' або почніть з /start.")
                await state.set_state(Form.date)
    except Exception as e:
        print(f"ОШИБКА [handlers.py]: під час спроби забронювати час: {type(e).__name__} - {e}", file=sys.stderr)
        await callback.message.answer(
            "Виникла критична помилка при спробі обробити ваш вибір. Будь ласка, почніть з /start.")
        await state.clear()


@main_router.message(StateFilter(Form.question))
async def get_question_handler(message: Message, state: FSMContext):
    """Отримує питання, зберігає його в FSM та запитує номер телефону для консультації."""
    question_text = message.text
    await state.update_data(question=question_text)
    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {message.from_user.id}")

    print(f"DEBUG [handlers.py]: Питання від {user_name} отримано: '{question_text}'. Запит номера телефону...",
          file=sys.stderr)

    await state.set_state(Form.booking_phone_number)
    # Використовуємо клавіатуру для поширення контакту
    keyboard = get_share_contact_keyboard()
    await message.answer(
        f"Дякую, ваше питання було: \"{question_text}\".\n\n"
        f"Тепер, будь ласка, поділіться вашим <b>номером телефону</b>. Він потрібен для зв'язку щодо консультації та узгодження деталей.\n"
        "Натисніть кнопку нижче або введіть номер вручну:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@main_router.message(StateFilter(Form.booking_phone_number), F.contact)
async def booking_phone_shared_handler(message: Message, state: FSMContext):
    """Обробляє номер телефону (поширений) для консультації та запитує месенджер."""
    phone_number = message.contact.phone_number
    await state.update_data(booking_phone_number=phone_number)
    user_data = await state.get_data()  # Оновлюємо дані
    user_name = user_data.get("name", f"User {message.from_user.id}")

    print(
        f"DEBUG [handlers.py]: Номер тел. '{phone_number}' (поширений) для конс. від {user_name} отримано. Запит месенджера...",
        file=sys.stderr)

    await state.set_state(Form.messenger_choice)
    keyboard = get_messenger_choice_keyboard()
    await message.answer(  # Відповідь без ReplyKeyboardRemove, оскільки клавіатура була one_time_keyboard
        f"Дякую! Ваш номер телефону: <code>{phone_number}</code>.\n"
        "Будь ласка, виберіть бажаний месенджер для відеодзвінка:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# Новий обробник для отримання номера телефону (введеного вручну)
@main_router.message(StateFilter(Form.booking_phone_number), F.text)
async def booking_phone_text_handler(message: Message, state: FSMContext):
    """Обробляє номер телефону (введений вручну) для консультації та запитує месенджер."""
    phone_number = message.text
    # Тут можна додати базову валідацію номера телефону, якщо потрібно
    await state.update_data(booking_phone_number=phone_number)
    user_data = await state.get_data()  # Оновлюємо дані
    user_name = user_data.get("name", f"User {message.from_user.id}")

    print(
        f"DEBUG [handlers.py]: Номер тел. '{phone_number}' (введений) для конс. від {user_name} отримано. Запит месенджера...",
        file=sys.stderr)

    await state.set_state(Form.messenger_choice)
    keyboard = get_messenger_choice_keyboard()
    await message.answer(  # Відповідь без ReplyKeyboardRemove
        f"Дякую! Ваш номер телефону: <code>{phone_number}</code>.\n"
        "Будь ласка, виберіть бажаний месенджер для відеодзвінка:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# Новий обробник для вибору месенджера та завершення бронювання
@main_router.callback_query(StateFilter(Form.messenger_choice), F.data.startswith("messenger_"))
async def messenger_choice_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє вибір месенджера та завершує бронювання."""
    await callback.answer()
    chosen_messenger_key = callback.data.split("messenger_")[1]
    chosen_messenger_text = MESSENGER_OPTIONS.get(chosen_messenger_key,
                                                  chosen_messenger_key.capitalize())  # Отримуємо читабельну назву

    await state.update_data(preferred_messenger=chosen_messenger_text)

    user_data = await state.get_data()
    user_name = user_data.get("name", f"User {callback.from_user.id}")
    selected_date = user_data.get("date")
    selected_time = user_data.get("time")
    question = user_data.get("question")
    booking_phone_number = user_data.get("booking_phone_number")  # Отримуємо номер телефону

    user_id = callback.from_user.id
    telegram_username = f"@{callback.from_user.username}" if callback.from_user.username else f"ID:{user_id}"

    if not all([selected_date, selected_time, question, booking_phone_number, chosen_messenger_text]):
        await callback.message.edit_text("Виникла помилка стану (не всі дані зібрано). Будь ласка, почніть з /start.")
        await state.clear()
        return

    try:
        g_client = get_gspread_client()
        sheet = g_client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)

        timestamp = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S")

        print(f"DEBUG [handlers.py]: Збереження запису для {user_name} з телефоном і месенджером...", file=sys.stderr)
        # Порядок колонок у Google Sheets:
        # Ім'я, Телеграм-контакт, Питання, User ID, Дата, Час, Час запису, Телефон (Консультація), Месенджер
        sheet.append_row([
            user_name,
            telegram_username,  # Контакт в Telegram
            question,
            str(user_id),
            selected_date,
            selected_time,
            timestamp,
            booking_phone_number,  # <<< НОВЕ ПОЛЕ
            chosen_messenger_text  # <<< НОВЕ ПОЛЕ
        ])
        print("DEBUG [handlers.py]: Запис збережено (з телефоном і месенджером).", file=sys.stderr)

        # Оновлюємо або використовуємо розширену функцію для повідомлення адміну
        await notify_admin_new_booking_extended(
            bot_instance=bot,  # Передаємо екземпляр бота
            admin_chat_id=ADMIN_CHAT_ID,
            user_name=user_name,
            selected_date=selected_date,
            selected_time=selected_time,
            question=question,
            telegram_username=telegram_username,
            user_id=user_id,
            timestamp=timestamp,
            booking_phone=booking_phone_number,  # <<< НОВИЙ ПАРАМЕТР
            preferred_messenger=chosen_messenger_text  # <<< НОВИЙ ПАРАМЕТР
        )

        await callback.message.edit_text(
            f"Дякую, {user_name}! Ваш запис на консультацію ({selected_date} {selected_time}) підтверджено!\n\n"
            f"<b>Ваш телефон:</b> <code>{booking_phone_number}</code>\n"
            f"<b>Бажаний месенджер:</b> {chosen_messenger_text}",
            parse_mode="HTML"
        )

        lawyer_contact = os.getenv("LAWYER_CONTACT_DETAILS", "контактні дані адвоката (тел/email)")
        payment_info = os.getenv("PAYMENT_DETAILS_TEXT", "реквізити для оплати будуть надіслані вам додатково")

        # Оновлюємо details_html, щоб відобразити отриманий телефон та месенджер
        details_html = (
            f"🗓️ <b>Деталі вашого запису:</b> {selected_date} о {selected_time}.\n\n"
            f"<b>Порядок проведення онлайн-консультації:</b>\n\n"
            f"1️⃣ <b>Платформа:</b> Ми зв'яжемося з вами за номером <code>{booking_phone_number}</code> (бажаний месенджер: {chosen_messenger_text}) незадовго до початку, щоб узгодити зручну платформу (Zoom, Google Meet, Teams, Viber, WhatsApp, Telegram тощо) та надати посилання.\n\n"
            f"2️⃣ <b>Підготовка:</b> Якщо ваше питання стосується документів, підготуйте їх копії/фото. Будь ласка, забезпечте стабільний інтернет та тихе місце.\n\n"
            f"3️⃣ <b>Оплата:</b> Вартість - <b>1000 грн/год</b>. {payment_info}\n\n"
            f"4️⃣ <b>Консультація:</b> Будьте готові обговорити ваше питання. Адвокат Меркович Богдан надасть вам необхідні роз'яснення та рекомендації.\n\n"
            f"5️⃣ <b>Зв'язок:</b> З термінових питань щодо запису <i>до</i> консультації звертайтесь: {lawyer_contact}.\n\n"
            f"Очікуйте на зв'язок для узгодження платформи!"
        )
        await callback.message.answer(details_html, parse_mode="HTML")

        await callback.message.answer(
            "Консультацію заплановано. Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear()

    except Exception as e:
        print(f"ОШИБКА [handlers.py]: збереження запису консультації (з месенджером): {type(e).__name__} - {e}",
              file=sys.stderr)
        await callback.message.answer("На жаль, сталася помилка під час фінального збереження вашого запису...")
        await callback.message.answer(
            "Бажаєте повернутися до головного меню?",
            reply_markup=get_back_to_main_menu_keyboard()
        )
        await state.clear()


# Обработчик для текстовых сообщений без установленного состояния
@main_router.message(StateFilter(None))  # StateFilter(None) ловит сообщения без активного состояния FSM
async def handle_unknown_text_messages(message: Message, state: FSMContext):
    # Можно добавить более интеллектуальный ответ или кнопки, если нужно
    await message.answer("Не розумію вас. Будь ласка, почніть з команди /start, щоб побачити доступні опції.")


@main_router.callback_query(F.data == "main_menu_start",
                            StateFilter(None))  # StateFilter(None) оскільки стан вже має бути очищений
async def back_to_main_menu_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє кнопку 'Повернутися на головне меню'."""
    await callback.answer()

    # Стан вже повинен бути очищений хендлером, який запропонував цю кнопку.
    # Але для певності можна викликати ще раз:
    await state.clear()

    user_id = callback.from_user.id
    display_name = None
    try:
        # Спробуємо отримати ім'я, яке користувач надавав раніше
        stored_name = get_client_provided_name(user_id)
        if stored_name:
            display_name = stored_name
            await state.update_data(name=display_name)  # Зберігаємо в FSM для show_service_choice_menu
    except Exception as e:
        print(f"DEBUG [handlers.py]: Не вдалося отримати ім'я для user {user_id} в main_menu_start: {e}",
              file=sys.stderr)

    # Використовуємо існуючу функцію для показу меню вибору послуг
    # Вона відредагує повідомлення, в якому була кнопка "Повернутися на головне меню"
    await show_service_choice_menu(callback, state, user_name=display_name)


# /root/telegram-schedule-bot/bot/handlers.py

async def show_available_dates_for_booking(target: types.TelegramObject, state: FSMContext, user_name: str):
    """Отримує та показує доступні дати для бронювання. Редагує повідомлення, якщо target - CallbackQuery."""
    message_to_edit_or_answer = None
    if isinstance(target, CallbackQuery):
        message_to_edit_or_answer = target.message
    elif isinstance(target, Message):
        message_to_edit_or_answer = target
    else:
        print("ERROR [handlers.py]: Неправильний тип target для show_available_dates_for_booking", file=sys.stderr)
        return

    try:
        print(f"DEBUG [handlers.py]: Користувач {user_name} переходить до вибору дати. Отримання дат...",
              file=sys.stderr)
        available_dates = get_available_dates()

        if not available_dates:
            no_dates_text = f"На жаль, {user_name}, зараз немає доступних дат для запису. Спробуйте пізніше."
            if isinstance(target, CallbackQuery):
                # Якщо немає дат, і це колбек, повертаємо до вибору послуг
                await message_to_edit_or_answer.edit_text(no_dates_text, reply_markup=get_service_choice_keyboard())
                await state.set_state(Form.service_choice)
            else:  # Якщо це повідомлення (після введення імені)
                await message_to_edit_or_answer.answer(no_dates_text)
                # І показуємо головне меню знову
                await show_service_choice_menu(message_to_edit_or_answer, state, user_name)
            return

        keyboard = get_dates_keyboard(available_dates)
        text_to_send = f"Дякую, {user_name}! Ось доступні дати для запису (на 7 днів):\nВиберіть дату:"

        if isinstance(target, CallbackQuery):
            await message_to_edit_or_answer.edit_text(text_to_send, reply_markup=keyboard)
        else:  # Message
            await message_to_edit_or_answer.answer(text_to_send, reply_markup=keyboard)

        await state.set_state(Form.date)

    except Exception as e:
        print(
            f"ОШИБКА [handlers.py]: отримання дат для {user_name} в show_available_dates_for_booking: {type(e).__name__} - {e}",
            file=sys.stderr)
        error_text = "Виникла помилка при отриманні списку дат."
        if isinstance(target, CallbackQuery):
            try:
                await message_to_edit_or_answer.edit_text(
                    f"{error_text} Будь ласка, спробуйте пізніше або поверніться до вибору послуг.",
                    reply_markup=get_service_choice_keyboard())
                await state.set_state(Form.service_choice)
            except:
                await message_to_edit_or_answer.answer(f"{error_text} Будь ласка, почніть з /start.")
                await state.clear()
        else:  # Message
            await message_to_edit_or_answer.answer(f"{error_text} Будь ласка, почніть з /start.")
            await state.clear()
