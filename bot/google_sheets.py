# /root/telegram-schedule-bot/bot/google_sheets.py

import gspread
# oauth2client застаріла, але залишаємо поки що, якщо ваш gspread < 5.0
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone  # Додано timezone
import sys  # Для логування в stderr
import os  # Потрібен для перевірки шляху
import copy
import pytz  # <<< ДОДАЙТЕ ЦЕЙ ІМПОРТ

# --- Налаштування ---
KYIV_TZ = pytz.timezone('Europe/Kiev')  # <<< ЧАСОВИЙ ПОЯС КИЄВА

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
STATUS_CANCELLED_BY_USER_IN_SCHEDULE = 'Вільно (скасовано клієнтом)' # Новий статус для Графіка

# Очікувані назви стовпців в аркуші "Заявки" (для пошуку та оновлення)
# Ці імена мають ТОЧНО відповідати заголовкам у вашому файлі Google Sheet "Заявки"
# В handlers.py при збереженні запису використовуються індекси, але для пошуку краще імена:
# [user_name, telegram_username, question, str(user_id), selected_date, selected_time, timestamp, booking_phone_number, chosen_messenger_text]
# Припускаємо такі заголовки в "Заявках" для пошуку (АДАПТУЙТЕ ЯКЩО ТРЕБА):
REQUEST_USER_ID_COLUMN = 'Telegram ID' # Назва колонки з ID користувача в аркуші "Заявки"
REQUEST_DATE_COLUMN = 'Дата'      # Назва колонки з датою запису в аркуші "Заявки"
REQUEST_TIME_COLUMN = 'Час'       # Назва колонки з часом запису в аркуші "Заявки"
REQUEST_STATUS_COLUMN = 'Статус Заявки' # Нова колонка для статусу заявки, напр. "Активна", "Скасовано клієнтом"
REQUEST_QUESTION_COLUMN = 'Питання'

CLIENTS_WORKSHEET_NAME = "Клиенты"  # Новая константа

# !!! ВАЖЛИВО: Вкажіть ТОЧНИЙ формат дати, який використовується у вашому стовпці 'Дата' в Google Sheets !!!
DATE_FORMAT_IN_SHEET = "%d.%m.%Y"

# Області доступу API
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# --- Налаштування Кешу ---
_CACHED_SCHEDULE_DATA = None
_LAST_SCHEDULE_FETCH_TIME = None
CACHE_TTL = timedelta(minutes=5)

# --- Авторизація ---
_CLIENT = None


def get_client_provided_name(user_id: int):
    """Шукає збережене ім'я клієнта. Повертає ім'я або None."""
    print(f"DEBUG: Getting client name for user_id: {user_id}...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(CLIENTS_WORKSHEET_NAME)
        target_cell = None
        try:
            target_cell = sheet.find(str(user_id), in_column=1)
        except gspread.exceptions.CellNotFound:
            print(f"DEBUG: CellNotFound caught for user_id: {user_id}.", file=sys.stderr)
            target_cell = None
        except Exception as e_find:
            print(f"ERROR during sheet.find() in get_client_provided_name: {type(e_find).__name__} - {e_find}",
                  file=sys.stderr)
            return None

        if target_cell:
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
    """Зберігає або оновлює ім'я клієнта, використовуючи час по Києву для позначок."""
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(CLIENTS_WORKSHEET_NAME)
        now_kyiv = datetime.now(KYIV_TZ)
        now_str = now_kyiv.strftime("%d.%m.%Y %H:%M:%S")
        target_cell = None
        try:
            target_cell = sheet.find(str(user_id), in_column=1)
        except gspread.exceptions.CellNotFound:
            target_cell = None
        except Exception as e_find:
            print(f"ERROR during sheet.find() in save_or_update_client_name: {type(e_find).__name__} - {e_find}", file=sys.stderr)
            return

        if target_cell:
            try:
                sheet.update_cell(target_cell.row, 2, telegram_username or "")
                sheet.update_cell(target_cell.row, 3, provided_name)
                sheet.update_cell(target_cell.row, 5, now_str)
            except Exception as e_update:
                print(f"ERROR updating client in '{CLIENTS_WORKSHEET_NAME}': {type(e_update).__name__} - {e_update}", file=sys.stderr)
        else:
            try:
                sheet.append_row([
                    str(user_id),
                    telegram_username or "",
                    provided_name,
                    now_str,
                    now_str
                ])
            except Exception as e_append:
                print(f"ERROR appending client in '{CLIENTS_WORKSHEET_NAME}': {type(e_append).__name__} - {e_append}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR in save_or_update_client_name: {type(e).__name__} - {e}", file=sys.stderr)


def get_gspread_client():
    global _CLIENT
    if _CLIENT is None:
        try:
            if not os.path.exists(SERVICE_ACCOUNT_FILE):
                error_msg = f"ERROR: Файл сервісного акаунту НЕ ЗНАЙДЕНО за шляхом: {SERVICE_ACCOUNT_FILE} (CWD: {os.getcwd()})"
                print(error_msg, file=sys.stderr)
                raise FileNotFoundError(error_msg)
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, SCOPE)
            _CLIENT = gspread.authorize(creds)
        except Exception as e:
            print(f"ПОМИЛКА АВТОРИЗАЦІЇ Google Sheets: {type(e).__name__} - {e}", file=sys.stderr)
            raise
    return _CLIENT


def invalidate_schedule_cache():
    global _CACHED_SCHEDULE_DATA, _LAST_SCHEDULE_FETCH_TIME
    _CACHED_SCHEDULE_DATA = None
    _LAST_SCHEDULE_FETCH_TIME = None
    print("DEBUG [google_sheets.py]: Кеш розкладу інвалідовано (скинуто).", file=sys.stderr)


def get_available_dates():
    global _CACHED_SCHEDULE_DATA, _LAST_SCHEDULE_FETCH_TIME
    now_kyiv = datetime.now(KYIV_TZ)
    now_utc = datetime.now(timezone.utc)

    if _CACHED_SCHEDULE_DATA is not None and \
            _LAST_SCHEDULE_FETCH_TIME is not None and \
            (now_utc - _LAST_SCHEDULE_FETCH_TIME) < CACHE_TTL:
        return copy.deepcopy(_CACHED_SCHEDULE_DATA)

    available_slots = {}
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        records = sheet.get_all_records()
        today_kyiv = now_kyiv.date()
        end_date_kyiv = today_kyiv + timedelta(days=7)
        processed_dates_temp = {}

        for record in records:
            date_str = record.get(DATE_COLUMN)
            time_val_sheet = record.get(TIME_COLUMN)
            status_val = record.get(STATUS_COLUMN)
            time_str_from_sheet = str(time_val_sheet).strip()

            if date_str and time_str_from_sheet and status_val and str(status_val).strip().lower() == STATUS_FREE:
                try:
                    record_date_obj = datetime.strptime(str(date_str), DATE_FORMAT_IN_SHEET).date()
                    if today_kyiv <= record_date_obj < end_date_kyiv:
                        parsed_time_for_slot = ""
                        try:
                            if ':' not in time_str_from_sheet:
                                if time_str_from_sheet.isdigit() and 0 <= int(time_str_from_sheet) <= 23:
                                    parsed_time_for_slot = f"{int(time_str_from_sheet):02d}:00"
                                else:
                                    continue
                            else:
                                parts = time_str_from_sheet.split(':')
                                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                    hour, minute = int(parts[0]), int(parts[1])
                                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                                        continue
                                    parsed_time_for_slot = f"{hour:02d}:{minute:02d}"
                                else:
                                    continue
                            record_time_obj = datetime.strptime(parsed_time_for_slot, "%H:%M").time()
                        except ValueError:
                            continue

                        slot_naive_dt = datetime.combine(record_date_obj, record_time_obj)
                        slot_kyiv_dt = KYIV_TZ.localize(slot_naive_dt)
                        if slot_kyiv_dt > now_kyiv:
                            if date_str not in processed_dates_temp:
                                processed_dates_temp[date_str] = []
                            processed_dates_temp[date_str].append(parsed_time_for_slot)
                except ValueError:
                    continue
        
        sorted_date_keys = sorted(
            processed_dates_temp.keys(),
            key=lambda d: datetime.strptime(d, DATE_FORMAT_IN_SHEET).date()
        )
        for date_key in sorted_date_keys:
            if processed_dates_temp[date_key]:
                available_slots[date_key] = sorted(processed_dates_temp[date_key])

        _CACHED_SCHEDULE_DATA = available_slots
        _LAST_SCHEDULE_FETCH_TIME = now_utc
        return copy.deepcopy(available_slots)

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ПОМИЛКА: Таблицю '{SPREADSHEET_NAME}' не знайдено.", file=sys.stderr)
        invalidate_schedule_cache()
        raise
    except gspread.exceptions.WorksheetNotFound:
        print(f"ПОМИЛКА: Аркуш '{SCHEDULE_WORKSHEET_NAME}' не знайдено.", file=sys.stderr)
        invalidate_schedule_cache()
        raise
    except KeyError as e:
        print(f"ПОМИЛКА: Відсутній стовпець в '{SCHEDULE_WORKSHEET_NAME}'. Помилка: {e}", file=sys.stderr)
        invalidate_schedule_cache()
        raise
    except Exception as e:
        print(f"ПОМИЛКА в get_available_dates: {type(e).__name__} - {e}", file=sys.stderr)
        invalidate_schedule_cache()
        raise


def update_status(date_str: str, time_str: str, new_status: str, expected_current_status: str = STATUS_FREE) -> bool:
    """
    Перевіряє, чи слот має очікуваний статус, оновлює його статус та інвалідує кеш.
    Повертає True, якщо статус успішно оновлено.
    Повертає False, якщо слот не знайдений, або його поточний статус не відповідає expected_current_status.
    Для скасування очікуваний статус буде STATUS_BOOKED, а новий - STATUS_FREE або STATUS_CANCELLED_BY_USER_IN_SCHEDULE.
    """
    print(f"Attempting to update status for {date_str} {time_str} from '{expected_current_status}' to '{new_status}'...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        all_data = sheet.get_all_values()
        if not all_data:
            print(f"ERROR in update_status: Sheet '{SCHEDULE_WORKSHEET_NAME}' is empty.", file=sys.stderr)
            return False
        header = all_data[0]
        try:
            date_col_idx = header.index(DATE_COLUMN)
            time_col_idx = header.index(TIME_COLUMN)
            status_col_idx = header.index(STATUS_COLUMN)
        except ValueError as e:
            print(f"ERROR in update_status: Column name missing in '{SCHEDULE_WORKSHEET_NAME}': {e}", file=sys.stderr)
            return False

        target_row_gspread_idx = None
        current_status_in_sheet = None
        for i, row_values in enumerate(all_data[1:], start=2): # gspread індекси рядків починаються з 1
            # Перевірка на наявність достатньої кількості елементів в рядку
            if len(row_values) > max(date_col_idx, time_col_idx, status_col_idx):
                if row_values[date_col_idx] == date_str and row_values[time_col_idx] == time_str:
                    target_row_gspread_idx = i
                    current_status_in_sheet = str(row_values[status_col_idx]).strip().lower()
                    break
            else:
                print(f"Warning in update_status: Row {i} in '{SCHEDULE_WORKSHEET_NAME}' has too few columns. Skipping.", file=sys.stderr)


        if target_row_gspread_idx:
            # Порівнюємо поточний статус в таблиці (в нижньому регістрі) з очікуваним (в нижньому регістрі)
            if current_status_in_sheet == expected_current_status.lower():
                sheet.update_cell(target_row_gspread_idx, status_col_idx + 1, new_status) # +1 бо gspread індекси колонок з 1
                print(f"Status updated for {date_str} {time_str} to '{new_status}'.", file=sys.stderr)
                invalidate_schedule_cache()
                return True
            else:
                print(f"Slot {date_str} {time_str} has status '{current_status_in_sheet}', but expected '{expected_current_status}'. Update failed.", file=sys.stderr)
                # Можливо, варто інвалідувати кеш, якщо статус не той, що очікувався, бо хтось інший міг його змінити
                invalidate_schedule_cache()
                return False
        else:
            print(f"ERROR: Slot for {date_str} {time_str} not found for update in '{SCHEDULE_WORKSHEET_NAME}'.", file=sys.stderr)
            return False

    except Exception as e:
        print(f"ERROR in update_status: {type(e).__name__} - {e}", file=sys.stderr)
        return False


def get_user_bookings(user_id: int) -> list:
    """
    Отримує список активних (майбутніх) бронювань для вказаного user_id з аркуша 'Заявки'.
    Повертає список словників, де кожен словник - це запис про бронювання.
    АБО список кортежів (row_index, data_dict) для легшого оновлення.
    """
    print(f"DEBUG [google_sheets.py]: Fetching active bookings for user_id: {user_id}...", file=sys.stderr)
    user_bookings = []
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        all_records = sheet.get_all_records() # Отримуємо як список словників

        now_kyiv = datetime.now(KYIV_TZ)

        # Визначення індексів потрібних колонок за їхніми назвами
        # Це більш надійно, ніж припускати фіксовані індекси
        # Якщо get_all_records() успішно виконано, то заголовки існують
        
        # Примітка: get_all_records() вже повертає дані з заголовками як ключами.
        # Нам потрібно знайти індекс рядка, якщо ми захочемо оновити його по індексу.
        # Або ми можемо знайти комірку за значенням user_id, date, time.
        # Для простоти, ми повернемо дані запису та його оригінальний індекс в таблиці.
        
        all_values = sheet.get_all_values()
        if not all_values:
            print(f"DEBUG [google_sheets.py]: No data in '{REQUESTS_WORKSHEET_NAME}' sheet.", file=sys.stderr)
            return []
            
        header = all_values[0]
        try:
            # Переконуємось, що необхідні колонки існують в заголовку
            # Якщо їх немає, функція має повернути порожній список або викликати помилку
            _ = header.index(REQUEST_USER_ID_COLUMN)
            _ = header.index(REQUEST_DATE_COLUMN)
            _ = header.index(REQUEST_TIME_COLUMN)
            # REQUEST_STATUS_COLUMN може ще не існувати, тому перевіряємо обережно
            request_status_col_idx = -1
            if REQUEST_STATUS_COLUMN in header:
                request_status_col_idx = header.index(REQUEST_STATUS_COLUMN)

        except ValueError as e:
            print(f"ПОМИЛКА [google_sheets.py]: Одна з обов'язкових колонок ('{REQUEST_USER_ID_COLUMN}', '{REQUEST_DATE_COLUMN}', '{REQUEST_TIME_COLUMN}') не знайдена в аркуші '{REQUESTS_WORKSHEET_NAME}'. Помилка: {e}", file=sys.stderr)
            return []


        for row_idx, record in enumerate(all_records, start=2): # start=2 бо get_all_records не включає заголовок, а індекси gspread з 1 (+1 для заголовка)
            record_user_id_str = str(record.get(REQUEST_USER_ID_COLUMN, '')).strip()
            record_date_str = record.get(REQUEST_DATE_COLUMN)
            record_time_str = record.get(REQUEST_TIME_COLUMN) # Може бути числовим або рядком "HH:MM"
            
            # Перевіряємо, чи статус заявки не "Скасовано" (якщо така колонка є)
            current_request_status = ""
            if request_status_col_idx != -1 and REQUEST_STATUS_COLUMN in record:
                 current_request_status = str(record.get(REQUEST_STATUS_COLUMN, "")).strip().lower()
            
            if current_request_status == "скасовано клієнтом" or \
               current_request_status == "cancelled by user":
                # print(f"DEBUG [google_sheets.py]: Skipping booking for user {record_user_id_str} on {record_date_str} {record_time_str} - already cancelled.", file=sys.stderr)
                continue


            if record_user_id_str == str(user_id) and record_date_str and record_time_str:
                try:
                    # Нормалізуємо час до формату HH:MM, якщо він числовий
                    normalized_time_str = record_time_str
                    if isinstance(record_time_str, (int, float)): # Якщо час це число (наприклад, 9, 10.5)
                        hour = int(record_time_str)
                        minute = int((record_time_str * 60) % 60)
                        normalized_time_str = f"{hour:02d}:{minute:02d}"
                    elif isinstance(record_time_str, str) and ':' not in record_time_str and record_time_str.isdigit():
                         normalized_time_str = f"{int(record_time_str):02d}:00"


                    booking_date_obj = datetime.strptime(record_date_str, DATE_FORMAT_IN_SHEET).date()
                    booking_time_obj = datetime.strptime(normalized_time_str, "%H:%M").time()
                    booking_datetime_naive = datetime.combine(booking_date_obj, booking_time_obj)
                    booking_datetime_kyiv = KYIV_TZ.localize(booking_datetime_naive)

                    if booking_datetime_kyiv > now_kyiv:
                        # Зберігаємо оригінальний індекс рядка для можливого оновлення
                        user_bookings.append({
                            "row_index": row_idx, # gspread-сумісний індекс рядка
                            "date": record_date_str,
                            "time": normalized_time_str, # Зберігаємо нормалізований час
                            "question": record.get(REQUEST_QUESTION_COLUMN, ""), # Адаптуйте назву колонки
                            "data": record # Повний запис, якщо потрібні інші поля
                        })
                except ValueError as e_parse:
                    print(f"ПОПЕРЕДЖЕННЯ [google_sheets.py]: Не вдалося розпарсити дату/час для запису user_id {user_id}: '{record_date_str} {record_time_str}'. Помилка: {e_parse}. Запис пропущено.", file=sys.stderr)
                    continue
        
        print(f"DEBUG [google_sheets.py]: Found {len(user_bookings)} active bookings for user_id {user_id}.", file=sys.stderr)
        # Сортуємо бронювання за датою та часом
        user_bookings.sort(key=lambda b: (datetime.strptime(b['date'], DATE_FORMAT_IN_SHEET).date(), datetime.strptime(b['time'], "%H:%M").time()))
        return user_bookings

    except gspread.exceptions.WorksheetNotFound:
        print(f"ПОМИЛКА [google_sheets.py]: Аркуш '{REQUESTS_WORKSHEET_NAME}' не знайдено при спробі отримати бронювання користувача.", file=sys.stderr)
        return []
    except KeyError as e:
        print(f"ПОМИЛКА [google_sheets.py]: Відсутня очікувана колонка в '{REQUESTS_WORKSHEET_NAME}' при отриманні бронювань: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"ПОМИЛКА в get_user_bookings для user_id {user_id}: {type(e).__name__} - {e}", file=sys.stderr)
        return []


def mark_booking_as_cancelled(row_index: int, user_name: str, user_id: int):
    """
    Оновлює запис про бронювання в аркуші 'Заявки', позначаючи його як скасоване.
    Наприклад, додає інформацію в нову колонку 'Статус Заявки' або до існуючої колонки 'Питання'.
    """
    print(f"DEBUG [google_sheets.py]: Marking booking at row {row_index} as cancelled for user_id: {user_id}...", file=sys.stderr)
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
        
        # Перевіряємо наявність колонки REQUEST_STATUS_COLUMN
        header = sheet.row_values(1) # Отримуємо заголовки
        status_col_letter = None
        notes_col_letter = None # Для резервного варіанту - додати до "Питання"

        try:
            status_col_idx = header.index(REQUEST_STATUS_COLUMN) + 1 # +1 для gspread індексації
            status_col_letter = gspread.utils.rowcol_to_a1(1, status_col_idx)[0] # Отримуємо літеру колонки
        except ValueError:
            print(f"ПОПЕРЕДЖЕННЯ [google_sheets.py]: Колонка '{REQUEST_STATUS_COLUMN}' не знайдена в '{REQUESTS_WORKSHEET_NAME}'. Спробую додати примітку до питання.", file=sys.stderr)
            # Якщо колонки статусу немає, спробуємо знайти колонку "Питання" для додавання примітки
            try:
                # Назва колонки "Питання" жорстко задана в handlers.py при append_row
                # Це може бути індекс 3 (D), якщо рахувати з 1 (A) для Ім'я, B для Telegram, C для Питання
                # Давайте знайдемо її за назвою "Питання" або припустимо індекс
                question_col_name_actual = "Питання" # Як використовується в handlers.py
                if question_col_name_actual in header:
                    notes_col_idx = header.index(question_col_name_actual) + 1
                    notes_col_letter = gspread.utils.rowcol_to_a1(1, notes_col_idx)[0]
                else: # Резервний варіант, якщо навіть "Питання" немає (малоймовірно)
                    print(f"ПОПЕРЕДЖЕННЯ [google_sheets.py]: Колонка '{question_col_name_actual}' також не знайдена. Скасування не буде детально позначено в аркуші 'Заявки'.", file=sys.stderr)

            except ValueError:
                 print(f"ПОПЕРЕДЖЕННЯ [google_sheets.py]: Резервна колонка 'Питання' не знайдена. Скасування не буде детально позначено.", file=sys.stderr)


        cancellation_note = f"Скасовано клієнтом ({user_name}, ID: {user_id}) о {datetime.now(KYIV_TZ).strftime('%d.%m.%Y %H:%M:%S')}"

        if status_col_letter:
            sheet.update_acell(f"{status_col_letter}{row_index}", "Скасовано клієнтом")
            # Можна додати детальнішу примітку в іншу колонку, якщо є
            # Наприклад, якщо є колонка "Примітки Адміністратора"
            print(f"DEBUG [google_sheets.py]: Booking at row {row_index} updated with status 'Скасовано клієнтом'.", file=sys.stderr)

        elif notes_col_letter: # Якщо є колонка "Питання"
            original_question = sheet.acell(f"{notes_col_letter}{row_index}").value or ""
            updated_question = f"{original_question} [INFO: {cancellation_note}]"
            sheet.update_acell(f"{notes_col_letter}{row_index}", updated_question)
            print(f"DEBUG [google_sheets.py]: Cancellation note added to question for booking at row {row_index}.", file=sys.stderr)
        else:
            print(f"INFO [google_sheets.py]: Не вдалося знайти підходящу колонку для позначки про скасування заявки в рядку {row_index}.", file=sys.stderr)
            # Тут можна просто нічого не робити, або додати новий стовпець, якщо є права і бажання
            
        return True

    except Exception as e:
        print(f"ПОМИЛКА в mark_booking_as_cancelled для рядка {row_index}: {type(e).__name__} - {e}", file=sys.stderr)
        return False

# Функція для збереження заявки (виклик з bot.py)
# Можна залишити в bot.py або перенести сюди для кращої організації
# def save_request(...)
#     client = get_gspread_client()
#     sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
#     sheet.append_row([...])
