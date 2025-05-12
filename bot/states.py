# /root/telegram-schedule-bot/bot/states.py
from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    """
    Определяет состояния для машины состояний (FSM) бота.
    """
    # Состояния для разных путей сбора имени
    callback_name = State()  # Имя для запроса на обратный звонок
    booking_name = State()  # Имя для записи на консультацию
    # Общие состояния
    service_choice = State()  # Ожидание выбора услуги (начальное состояние после /start)
    phone_number = State()  # Ожидание номера телефона (для обратного звонка)
    date = State()  # Ожидание выбора даты консультации
    time = State()  # Ожидание выбора времени консультации
    question = State()  # Ожидание вопроса для консультации
    booking_phone_number = State()  # <<< НОВИЙ СТАН: для номера телефону при записі на консультацію
    messenger_choice = State()  # <<< НОВИЙ СТАН: для вибору месенджера
    renaming_name = State()  # <<< НОВИЙ СТАН для зміни імені