# /root/telegram-schedule-bot/bot/google_sheets.py

import gspread
# oauth2client застаріла, але залишаємо поки що, якщо ваш gspread < 5.0
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone  # Додано timezone
import sys  # Для логування в stderr
import os  # Потрібен для перевірки шляху
import copy

# --- Налаштування ---
# !!! ЗАМІНІТЬ 'telegram-schedule-bot' НА ВАШУ РЕАЛЬНУ НАЗВУ ПАПКИ !!!
# SERVICE_ACCOUNT_FILE = '/root/telegram-schedule-bot/creds.json'
SERVICE_ACCOUNT_FILE = 'creds.json'
# Переконайтесь, що назви таблиці та аркушів ТОЧНО відповідають вашим у Google Sheets
SPREADSHEET_NAME = "ClientRequests"
SCHEDULE_WORKSHEET_NAME = "Графік"
REQUESTS_WORKSHEET_NAME = "Заявки"  # Потрібно для збереження запитів

# Очікувані назви стовпців в аркуші "Графік" (регістр важливий!)
DATE_COLUMN = 'Дата'
TIME_COLUMN = 'Час'
STATUS_COLUMN = 'Статус'
STATUS_FREE = 'вільно'  # Статус вільного часу (у нижньому регістрі для порівняння)
STATUS_BOOKED = 'Заброньовано'  # Статус для оновлення

CLIENTS_WORKSHEET_NAME = "Клиенты"  # Новая константа

# !!! ВАЖЛИВО: Вкажіть ТОЧНИЙ формат дати, який використовується у вашому стовпці 'Дата' в Google Sheets !!!
# Приклади: "%d.%m.%Y" для "05.05.2025", "%Y-%m-%d" для "2025-05-05"
DATE_FORMAT_IN_SHEET = "%d.%m.%Y"

# Області доступу API
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# --- Налаштування Кешу ---
_CACHED_SCHEDULE_DATA = None  # Тут буде зберігатися кеш { 'дата_рядок': ['час1', 'час2'], ... }
_LAST_SCHEDULE_FETCH_TIME = None
CACHE_TTL = timedelta(minutes=5)  # Час життя кешу, наприклад 5 хвилин

# --- Авторизація ---
_CLIENT = None  # Кешуємо клієнт для ефективності


def get_client_provided_name(user_id: int):
    """Шукає збережене ім'я клієнта. Повертає ім'я або None."""
    print(f"DEBUG: Getting client name for user_id: {user_id}...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(CLIENTS_WORKSHEET_NAME)
        target_cell = None
        try:
            # find може генерувати CellNotFound в СТАРИХ версіях,
            # або повертати None/генерувати іншу помилку в нових при не знаходженні.
            # Краще перевіряти результат.
            target_cell = sheet.find(str(user_id), in_column=1)
        except gspread.exceptions.CellNotFound: # Залишаємо про всяк випадок для старих версій
             print(f"DEBUG: CellNotFound caught for user_id: {user_id}.", file=sys.stderr)
             target_cell = None # Явно вказуємо, що не знайдено
        except Exception as e_find:
             print(f"ERROR during sheet.find() in get_client_provided_name: {type(e_find).__name__} - {e_find}", file=sys.stderr)
             return None # Помилка пошуку

        if target_cell:
            # Знайдено, припускаємо, що ім'я в колонці C (індекс 2)
            provided_name = sheet.cell(target_cell.row, 3).value
            if provided_name:
                print(f"DEBUG: Found name '{provided_name}' for user_id {user_id}.", file=sys.stderr)
                return str(provided_name)
            else:
                print(f"DEBUG: Found user_id {user_id}, but name is empty.", file=sys.stderr)
                return None
        else:
            print(f"DEBUG: Client with user_id {user_id} not found.", file=sys.stderr)
            return None
    except Exception as e:
        print(f"ERROR in get_client_provided_name: {type(e).__name__} - {e}", file=sys.stderr)
        return None

def save_or_update_client_name(user_id: int, telegram_username: str, provided_name: str):
    """Зберігає або оновлює ім'я клієнта."""
    print(f"DEBUG: Saving/Updating client name for user_id: {user_id}, name: {provided_name}...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(CLIENTS_WORKSHEET_NAME)
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        target_cell = None
        try:
            target_cell = sheet.find(str(user_id), in_column=1)
        except gspread.exceptions.CellNotFound: # Для старих версій
            target_cell = None
        except Exception as e_find:
             print(f"ERROR during sheet.find() in save_or_update_client_name: {type(e_find).__name__} - {e_find}", file=sys.stderr)
             # У разі помилки пошуку, не намагаємося додавати/оновлювати
             return

        if target_cell:
            # ЗНАЙДЕНО - Оновлюємо
            try:
                sheet.update_cell(target_cell.row, 2, telegram_username or "") # Username (B)
                sheet.update_cell(target_cell.row, 3, provided_name)         # Name (C)
                sheet.update_cell(target_cell.row, 5, now_str)               # last_seen (E)
                print(f"DEBUG: Updated client name for user_id: {user_id}", file=sys.stderr)
            except Exception as e_update:
                 print(f"ERROR updating client in '{CLIENTS_WORKSHEET_NAME}': {type(e_update).__name__} - {e_update}", file=sys.stderr)
        else:
            # НЕ ЗНАЙДЕНО - Додаємо новий рядок
            try:
                sheet.append_row([
                    str(user_id),         # telegram_user_id (A)
                    telegram_username or "", # telegram_username (B)
                    provided_name,      # provided_name (C)
                    now_str,            # first_seen (D)
                    now_str             # last_seen (E)
                ])
                print(f"DEBUG: Added new client with user_id: {user_id}", file=sys.stderr)
            except Exception as e_append:
                 print(f"ERROR appending client in '{CLIENTS_WORKSHEET_NAME}': {type(e_append).__name__} - {e_append}", file=sys.stderr)

    except Exception as e:
        print(f"ERROR in save_or_update_client_name: {type(e).__name__} - {e}", file=sys.stderr)

# --- Авторизація ---
def get_gspread_client():
    global _CLIENT
    if _CLIENT is None:
        # print("DEBUG: Attempting to authorize Google Sheets client...", file=sys.stderr)
        try:
            if not os.path.exists(SERVICE_ACCOUNT_FILE):
                error_msg = f"ERROR: Файл сервісного акаунту НЕ ЗНАЙДЕНО за шляхом: {SERVICE_ACCOUNT_FILE} (CWD: {os.getcwd()})"
                # print(error_msg, file=sys.stderr)
                raise FileNotFoundError(error_msg)
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, SCOPE)
            _CLIENT = gspread.authorize(creds)
            # print("Авторизація в Google Sheets успішна.", file=sys.stderr)
        except Exception as e:
            # print(f"ПОМИЛКА АВТОРИЗАЦІЇ Google Sheets: {type(e).__name__} - {e}", file=sys.stderr)
            raise
    return _CLIENT


# --- Функція для інвалідації (скидання) кешу ---
def invalidate_schedule_cache():
    """Скидає кеш розкладу."""
    global _CACHED_SCHEDULE_DATA, _LAST_SCHEDULE_FETCH_TIME
    _CACHED_SCHEDULE_DATA = None
    _LAST_SCHEDULE_FETCH_TIME = None
    # print("DEBUG: Кеш розкладу інвалідовано (скинуто).", file=sys.stderr)


# --- Отримання доступних слотів (з кешуванням) ---
def get_available_dates():
    """
    Отримує доступні дати та час з кешу або з аркуша 'Графік',
    фільтруючи за статусом 'вільно' та за датою (наступні 7 днів).
    """
    global _CACHED_SCHEDULE_DATA, _LAST_SCHEDULE_FETCH_TIME
    now = datetime.now(timezone.utc)  # Використовуємо timezone-aware datetime

    # Перевіряємо кеш
    if _CACHED_SCHEDULE_DATA is not None and \
            _LAST_SCHEDULE_FETCH_TIME is not None and \
            (now - _LAST_SCHEDULE_FETCH_TIME) < CACHE_TTL:
        # print("DEBUG: Повернення доступних дат з КЕШУ.", file=sys.stderr)
        # Повертаємо глибоку копію, щоб випадково не змінити кеш
        return copy.deepcopy(_CACHED_SCHEDULE_DATA)

    # print(f"DEBUG: Кеш застарів або порожній. Завантаження актуальних дат з Google Sheets...", file=sys.stderr)
    available_slots = {}  # Змінено з available_dates на available_slots для ясності
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        # print(f"Аркуш '{SCHEDULE_WORKSHEET_NAME}' відкрито. Отримання записів...", file=sys.stderr)
        records = sheet.get_all_records()  # Читаємо всі дані
        # print(f"Отримано {len(records)} записів.", file=sys.stderr)

        today = date.today()
        end_date = today + timedelta(days=7)
        processed_dates_temp = {}

        for record in records:
            date_str = record.get(DATE_COLUMN)
            time_val = record.get(TIME_COLUMN)
            status_val = record.get(STATUS_COLUMN)

            if date_str and time_val and status_val and str(status_val).strip().lower() == STATUS_FREE:
                try:
                    record_date_obj = datetime.strptime(str(date_str), DATE_FORMAT_IN_SHEET).date()
                    if today <= record_date_obj < end_date:
                        if date_str not in processed_dates_temp:
                            processed_dates_temp[date_str] = []
                        processed_dates_temp[date_str].append(str(time_val))
                except ValueError:
                    # print(
                    #     f"Попередження: Не розпарсено дату '{date_str}' в форматі '{DATE_FORMAT_IN_SHEET}'. Пропущено.",
                    #     file=sys.stderr)
                    continue

        sorted_date_keys = sorted(processed_dates_temp.keys(),
                                  key=lambda d: datetime.strptime(d, DATE_FORMAT_IN_SHEET).date())
        for date_key in sorted_date_keys:
            available_slots[date_key] = sorted(processed_dates_temp[date_key])

        # Зберігаємо в кеш
        _CACHED_SCHEDULE_DATA = available_slots
        _LAST_SCHEDULE_FETCH_TIME = now
        # print(f"DEBUG: Кеш оновлено новими даними. TTL: {CACHE_TTL}. Слоти: {available_slots}", file=sys.stderr)
        return copy.deepcopy(available_slots)  # Повертаємо копію

        # print(f"Знайдено доступні слоти: {available_dates}")
        # return available_dates
        # return available_slots
    except gspread.exceptions.SpreadsheetNotFound:
        # print(f"ПОМИЛКА: Таблицю '{SPREADSHEET_NAME}' не знайдено. Перевірте назву та доступ.")
        raise
    except gspread.exceptions.WorksheetNotFound:
        # print(f"ПОМИЛКА: Аркуш '{SCHEDULE_WORKSHEET_NAME}' не знайдено. Перевірте назву.")
        raise
    except KeyError as e:
        # print(
        #     f"ПОМИЛКА: Відсутній необхідний стовпець в аркуші '{SCHEDULE_WORKSHEET_NAME}' (очікувались '{DATE_COLUMN}', '{TIME_COLUMN}', '{STATUS_COLUMN}'). Помилка: {e}")
        raise
    except Exception as e:
        # print(f"ПОМИЛКА в get_available_dates: {type(e).__name__} - {e}", file=sys.stderr)
        invalidate_schedule_cache()  # Скидаємо кеш у разі будь-якої помилки завантаження
        raise


# --- Оновлення статусу (з інвалідацією кешу) ---
def update_status(date_str, time_str, new_status=STATUS_BOOKED):
    """
    Перевіряє, чи слот вільний, оновлює його статус та інвалідує кеш.
    Повертає True, якщо статус успішно оновлено.
    Повертає False, якщо слот вже був зайнятий або не знайдений.
    """
    # print(f"Attempting to check and update status for {date_str} {time_str} to '{new_status}'...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        # ... (логіка пошуку target_row_gspread_idx та current_status_in_sheet як у попередній версії) ...
        all_data = sheet.get_all_values()  # Потрібно для перевірки поточного статусу
        if not all_data: return False  # Аркуш порожній
        header = all_data[0]
        try:
            date_col_idx = header.index(DATE_COLUMN)
            time_col_idx = header.index(TIME_COLUMN)
            status_col_idx = header.index(STATUS_COLUMN)
        except ValueError as e:
            # print(f"ERROR: Column name missing: {e}", file=sys.stderr)
            return False

        target_row_gspread_idx = None
        current_status_in_sheet = None
        for i, row_values in enumerate(all_data[1:], start=2):
            if row_values[date_col_idx] == date_str and row_values[time_col_idx] == time_str:
                target_row_gspread_idx = i
                current_status_in_sheet = str(row_values[status_col_idx]).strip().lower()
                break

        if target_row_gspread_idx:
            if current_status_in_sheet == STATUS_FREE:
                sheet.update_cell(target_row_gspread_idx, status_col_idx + 1, new_status)
                # print(f"Status updated for {date_str} {time_str} to '{new_status}'.", file=sys.stderr)
                invalidate_schedule_cache()  # !!! Скидаємо кеш після успішного оновлення !!!
                return True
            else:
                # print(f"Slot {date_str} {time_str} already '{current_status_in_sheet}'. Booking failed.",
                #       file=sys.stderr)
                return False
        else:
            # print(f"ERROR: Slot for {date_str} {time_str} not found for update.", file=sys.stderr)
            return False

    except Exception as e:
        # print(f"ERROR in update_status: {type(e).__name__} - {e}", file=sys.stderr)
        # У разі помилки API, кеш не інвалідуємо, бо дані могли не змінитися
        return False

# Функція для збереження заявки (виклик з bot.py)
# Можна залишити в bot.py або перенести сюди для кращої організації
# def save_request(...)
#     client = get_gspread_client()
#     sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
#     sheet.append_row([...])
