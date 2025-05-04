# /root/telegram-schedule-bot/bot/google_sheets.py

import gspread
# oauth2client застаріла, але залишаємо поки що, якщо ваш gspread < 5.0
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os # Потрібен для перевірки шляху

# --- Налаштування ---
# !!! ЗАМІНІТЬ 'telegram-schedule-bot' НА ВАШУ РЕАЛЬНУ НАЗВУ ПАПКИ !!!
# SERVICE_ACCOUNT_FILE = '/root/telegram-schedule-bot/creds.json'
SERVICE_ACCOUNT_FILE = 'creds.json'
# Переконайтесь, що назви таблиці та аркушів ТОЧНО відповідають вашим у Google Sheets
SPREADSHEET_NAME = "ClientRequests"
SCHEDULE_WORKSHEET_NAME = "Графік"
REQUESTS_WORKSHEET_NAME = "Заявки" # Потрібно для збереження запитів

# Очікувані назви стовпців в аркуші "Графік" (регістр важливий!)
DATE_COLUMN = 'Дата'
TIME_COLUMN = 'Час'
STATUS_COLUMN = 'Статус'
STATUS_FREE = 'вільно' # Статус вільного часу (у нижньому регістрі для порівняння)
STATUS_BOOKED = 'Заброньовано' # Статус для оновлення

# Області доступу API
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# --- Авторизація ---
def get_gspread_client():
    """Авторизується та повертає клієнт gspread."""
    try:
        # Перевірка існування файлу ключа
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            error_msg = f"ERROR: Файл сервісного акаунту НЕ ЗНАЙДЕНО за шляхом: {SERVICE_ACCOUNT_FILE}"
            print(error_msg)
            raise FileNotFoundError(error_msg)

        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, SCOPE)
        client = gspread.authorize(creds)
        print("Авторизація в Google Sheets успішна.") # Лог успіху
        return client
    except FileNotFoundError as e:
        print(f"ПОМИЛКА АВТОРИЗАЦІЇ (Файл не знайдено): {e}")
        raise # Перекидаємо помилку далі
    except Exception as e:
        # Логуємо будь-яку іншу помилку авторизації
        print(f"ПОМИЛКА АВТОРИЗАЦІЇ Google Sheets: {type(e).__name__} - {e}")
        raise # Перекидаємо помилку далі, щоб її спіймав бот

# --- Отримання доступних слотів ---
def get_available_dates():
    """Отримує доступні дати та час з аркуша 'Графік'."""
    print(f"Спроба отримати доступні дати з аркуша '{SCHEDULE_WORKSHEET_NAME}'...")
    available_dates = {}
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        print(f"Аркуш '{SCHEDULE_WORKSHEET_NAME}' відкрито. Отримання записів...")
        # Використовуємо get_all_records(), припускаючи, що перший рядок - заголовки
        records = sheet.get_all_records()
        print(f"Отримано {len(records)} записів.")

        for record in records:
            # Безпечно отримуємо значення, перевіряючи наявність ключів
            date_val = record.get(DATE_COLUMN)
            time_val = record.get(TIME_COLUMN)
            status_val = record.get(STATUS_COLUMN)

            # Перевіряємо, чи всі потрібні дані є, і чи статус 'вільно'
            if date_val and time_val and status_val and str(status_val).strip().lower() == STATUS_FREE:
                if date_val not in available_dates:
                    available_dates[date_val] = []
                available_dates[date_val].append(time_val)

        print(f"Знайдено доступні слоти: {available_dates}")
        return available_dates
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ПОМИЛКА: Таблицю '{SPREADSHEET_NAME}' не знайдено. Перевірте назву та доступ.")
        raise
    except gspread.exceptions.WorksheetNotFound:
        print(f"ПОМИЛКА: Аркуш '{SCHEDULE_WORKSHEET_NAME}' не знайдено. Перевірте назву.")
        raise
    except KeyError as e:
        print(f"ПОМИЛКА: Відсутній необхідний стовпець в аркуші '{SCHEDULE_WORKSHEET_NAME}' (очікувались '{DATE_COLUMN}', '{TIME_COLUMN}', '{STATUS_COLUMN}'). Помилка: {e}")
        raise
    except Exception as e:
        print(f"ПОМИЛКА в get_available_dates: {type(e).__name__} - {e}")
        raise # Перекидаємо помилку далі

# --- Оновлення статусу ---
def update_status(date, time, status=STATUS_BOOKED):
    """Оновлює статус для певного слоту часу в аркуші 'Графік'."""
    print(f"Спроба оновити статус для {date} {time} на '{status}' в аркуші '{SCHEDULE_WORKSHEET_NAME}'...")
    try:
        client = get_gspread_client()
        sheet = client.open(SPREADSHEET_NAME).worksheet(SCHEDULE_WORKSHEET_NAME)
        print(f"Аркуш '{SCHEDULE_WORKSHEET_NAME}' відкрито для оновлення статусу.")

        # Шукаємо рядок, що відповідає даті та часу
        # Припускаємо: Колонка 1 = Дата, Колонка 2 = Час, Колонка 3 = Статус
        # !!! Ця логіка може потребувати адаптації під ВАШУ структуру таблиці !!!
        target_row = None
        try:
            # Знаходимо всі комірки з потрібною датою в першій колонці
            date_cells = sheet.findall(date, in_column=1)
            for cell in date_cells:
                # Перевіряємо час у сусідній (другій) колонці
                time_in_cell = sheet.cell(cell.row, 2).value
                if time_in_cell == time:
                    target_row = cell.row # Знайшли потрібний рядок
                    break
        except gspread.exceptions.CellNotFound:
             print(f"Попередження: Не знайдено комірок з датою '{date}' у колонці 1.")
             # Можна нічого не робити, або повернути помилку, якщо це неочікувано
             pass # Просто виходимо, якщо дата не знайдена

        if target_row:
            # Оновлюємо статус у третій колонці знайденого рядка
            sheet.update_cell(target_row, 3, status)
            print(f"Статус для {date} {time} успішно оновлено на '{status}' у рядку {target_row}.")
        else:
            # Якщо рядок не знайдено - логуємо це
            print(f"ПОМИЛКА: Не знайдено рядок з датою '{date}' та часом '{time}' для оновлення статусу.")
            # Можливо, варто викликати виняток, щоб бот знав про проблему
            # raise ValueError(f"Не знайдено слот для оновлення статусу: {date} {time}")

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ПОМИЛКА: Таблицю '{SPREADSHEET_NAME}' не знайдено. Перевірте назву та доступ.")
        raise
    except gspread.exceptions.WorksheetNotFound:
        print(f"ПОМИЛКА: Аркуш '{SCHEDULE_WORKSHEET_NAME}' не знайдено. Перевірте назву.")
        raise
    except Exception as e:
        print(f"ПОМИЛКА в update_status: {type(e).__name__} - {e}")
        raise

# Функція для збереження заявки (виклик з bot.py)
# Можна залишити в bot.py або перенести сюди для кращої організації
# def save_request(...)
#     client = get_gspread_client()
#     sheet = client.open(SPREADSHEET_NAME).worksheet(REQUESTS_WORKSHEET_NAME)
#     sheet.append_row([...])
