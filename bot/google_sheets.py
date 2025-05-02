import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

SHEET_NAME = "ClientRequests"
WORKSHEET_NAME = "Заявки"

def save_to_sheet(name, contact, question, telegram_id):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)

    sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)

    row = [name, contact, question, str(telegram_id), datetime.now().strftime("%d.%m.%Y %H:%M")]
    sheet.append_row(row)

