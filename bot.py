import asyncio
import requests
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "<8291777944:AAEgFfl3a-A3Z6yj5v23egmyDUYTbERrvNA>"
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ----------------------
# База данных
# ----------------------
conn = sqlite3.connect("dating.db")
cursor = conn.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    nickname TEXT,
                    age INTEGER,
                    gender TEXT,
                    bio TEXT,
                    interests TEXT
                 )""")
conn.commit()

# ----------------------
# FSM для регистрации профиля
# ----------------------
class ProfileStates(StatesGroup):
    nickname = State()
    age = State()
    gender = State()
    bio = State()
    interests = State()

# ----------------------
# Очередь и активные чаты
# ----------------------
waiting_users = []
active_chats = {}

# ----------------------
# Получение объявления SSP/RichAds
# ----------------------
def get_richads(telegram_id: int, publisher_id="988067", widget_id="372811", bid_floor=0.0001, language_code="en"):
    url = "http://15068.xml.adx1.com/telegram-mb"
    payload = {
        "language_code": language_code,
        "publisher_id": publisher_id,
        "widget_id": widget_id,
        "bid_floor": bid_floor,
        "telegram_id": str(telegram_id),
        "production": True
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            ads = response.json()
            if ads:
                return ads[0]  # Берем первое объявление
        return None
    except Exception as e:
        print(f"Error getting ad: {e}")
        return None

async def send_ad_to_user(user_id: int, ad: dict):
    if not ad:
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=ad.get("button", "Click"), url=ad.get("link"))]]
    )
    await bot.send_photo(
        chat_id=user_id,
        photo=ad.get("image"),
        caption=f"{ad.get('title')}\n\n{ad.get('message')}",
        reply_markup=keyboard
    )

# ----------------------
# Регистрация профиля
# ----------------------
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    telegram_id = message.from_user.id
    cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    user = cursor.fetchone()
    if not user:
        await message.answer("Привет! Давай создадим твой профиль. Введите никнейм:")
        await ProfileStates.nickname.set()
    else:
        await message.answer("Вы уже зарегистрированы. Используйте /next для поиска собеседника.")

@dp.message_handler(state=ProfileStates.nickname)
async def process_nickname(message: types.Message, state: FSMContext):
    await state.update_data(nickname=message.text)
    await message.answer("Введите ваш возраст:")
    await ProfileStates.next()

@dp.message_handler(state=ProfileStates.age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите корректный возраст цифрами:")
        return
    await state.update_data(age=int(message.text))
    await message.answer("Укажите ваш пол (М/Ж):")
    await ProfileStates.next()

@dp.message_handler(state=ProfileStates.gender)
async def process_gender(message: types.Message, state: FSMContext):
    if message.text.upper() not in ["М", "Ж"]:
        await message.answer("Введите М или Ж:")
        return
    await state.update_data(gender=message.text.upper())
    await message.answer("Напишите короткое описание о себе:")
    await ProfileStates.next()

@dp.message_handler(state=ProfileStates.bio)
async def process_bio(message: types.Message, state: FSMContext):
    await state.update_data(bio=message.text)
    await message.answer("Укажите ваши интересы через запятую:")
    await ProfileStates.next()

@dp.message_handler(state=ProfileStates.interests)
async def process_interests(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute(
        "INSERT OR REPLACE INTO users (telegram_id, nickname, age, gender, bio, interests) VALUES (?, ?, ?, ?, ?, ?)",
        (message.from_user.id, data['nickname'], data['age'], data['gender'], data['bio'], message.text)
    )
    conn.commit()
    await message.answer("Профиль создан! Используйте /next для поиска собеседника.")
    await state.finish()

# ----------------------
# Поиск нового собеседника с показом рекламы
# ----------------------
@dp.message_handler(commands=['next'])
async def next_chat(message: types.Message):
    user_id = message.from_user.id

    # 1. Сначала показать рекламу
    ad = get_richads(user_id)
    if ad:
        await send_ad_to_user(user_id, ad)

    # 2. Поиск партнера
    cursor.execute("SELECT * FROM users WHERE telegram_id!=?", (user_id,))
    candidates = cursor.fetchall()
    partner_id = None
    for c in candidates:
        pid = c[0]
        if pid not in active_chats and pid not in waiting_users:
            partner_id = pid
            break

    if partner_id:
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        await bot.send_message(user_id, "Собеседник найден! Можете писать.")
        await bot.send_message(partner_id, "Собеседник найден! Можете писать.")
    else:
        waiting_users.append(user_id)
        await message.answer("Ждем подходящего собеседника...")

# ----------------------
# Выйти из чата
# ----------------------
@dp.message_handler(commands=['stop'])
async def stop_chat(message: types.Message):
    user_id = message.from_user.id
    if user_id in active_chats:
        partner_id = active_chats.pop(user_id)
        active_chats.pop(partner_id, None)
        await bot.send_message(partner_id, "Собеседник вышел из чата.")
        await message.answer("Вы вышли из чата.")
    elif user_id in waiting_users:
        waiting_users.remove(user_id)
        await message.answer("Вы вышли из очереди поиска.")

# ----------------------
# Пересылка сообщений между пользователями
# ----------------------
@dp.message_handler(content_types=types.ContentType.ANY)
async def forward_message(message: types.Message):
    user_id = message.from_user.id
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        if message.text:
            await bot.send_message(partner_id, message.text)
        elif message.photo:
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption or "")
        elif message.voice:
            await bot.send_voice(partner_id, message.voice.file_id)
        elif message.audio:
            await bot.send_audio(partner_id, message.audio.file_id)
        elif message.video:
            await bot.send_video(partner_id, message.video.file_id)
        elif message.document:
            await bot.send_document(partner_id, message.document.file_id)
        else:
            await message.answer("Тип сообщения не поддерживается.")
    else:
        await message.answer("Вы не в чате. Используйте /next для поиска собеседника.")

# ----------------------
# Запуск бота
# ----------------------
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
