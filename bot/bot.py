from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from google_sheets import save_to_sheet
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Form(StatesGroup):
    name = State()
    contact = State()
    question = State()

@dp.message(F.text == "/start")
async def start(message: Message, state: FSMContext):
    await state.set_state(Form.name)
    await message.answer("👋 Вітаю! Як вас звати?")

@dp.message(Form.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Form.contact)
    await message.answer("📱 Вкажіть, будь ласка, ваш контакт (телефон або Telegram):")

@dp.message(Form.contact)
async def get_contact(message: Message, state: FSMContext):
    await state.update_data(contact=message.text)
    await state.set_state(Form.question)
    await message.answer("📝 Коротко опишіть суть вашого питання:")

@dp.message(Form.question)
async def get_question(message: Message, state: FSMContext):
    data = await state.update_data(question=message.text)
    await state.clear()

    # Збереження в Google Таблицю
    save_to_sheet(
        name=data["name"],
        contact=data["contact"],
        question=data["question"],
        telegram_id=message.from_user.id,
    )

    await message.answer("✅ Дякую! Я отримав вашу заявку та зв’яжуся з вами найближчим часом.")

