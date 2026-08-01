import asyncio
from datetime import datetime, timedelta
import logging
import random
import sqlite3
import sys
import os
import threading
import time
import telebot
from telebot import types

# ==============================================================================
# 1. КОНФИГУРАЦИЯ И НАСТРОЙКА БОТА
# ==============================================================================

TOKEN = "8320216944:AAE2PhFNEIu6Yg1nxppjIRQOt1Z2noOX-Jc"
ADMIN_ID = 5095702210  # Telegram ID администратора
ADMIN_CARD = "2200 7012 3674 6712 (Т-Банк)"
ADMIN_WALLET = "UQCEys8Frn_276y6a2p15ZbPJEjsKLhotfv9gDARyIoIOD1G"
CHANNEL_USERNAME = "@CoinFarmEmpire"  # Юзернейм канала для обязательной подписки

# Настройка логирования для отслеживания работы на Render
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("CoinFarmBot")

# Инициализация бота
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Словарь для хранения состояний пользователей (вместо FSM из aiogram)
user_states = {}

# ==============================================================================
# 2. ИГРОВАЯ ЭКОНОМИКА И ТАБЛИЦЫ НАГРАД
# ==============================================================================

# Таблица эксклюзивных майнеров
EXCLUSIVE_MINERS = {
    "miner_1": {
        "name": "⚡ Miner Usual",
        "speed": 0.05,
        "stars": 99,
        "rub": 150.0,
        "gram": 1.2,
        "usdt": 1.6,
        "description": "Базовый эксклюзивный майнер для начального ускорения добычи."
    },
    "miner_2": {
        "name": "🔥 Miner Turbo",
        "speed": 0.10,
        "stars": 199,
        "rub": 300.0,
        "gram": 2.4,
        "usdt": 3.2,
        "description": "Продвинутый майнер с удвоенной скоростью генерации монет."
    },
    "miner_3": {
        "name": "💎 Miner Monster",
        "speed": 0.20,
        "stars": 349,
        "rub": 550.0,
        "gram": 4.3,
        "usdt": 5.8,
        "description": "Мощная станция для серьезного пассивного дохода."
    },
    "miner_4": {
        "name": "🚀 Miner Quantum",
        "speed": 0.35,
        "stars": 499,
        "rub": 800.0,
        "gram": 6.2,
        "usdt": 8.5,
        "description": "Квантовый майнер, обеспечивающий высочайший поток крипты."
    },
    "miner_5": {
        "name": "👑 Miner Cyber",
        "speed": 0.50,
        "stars": 749,
        "rub": 1200.0,
        "gram": 9.4,
        "usdt": 12.8,
        "description": "Кибернетический флагман с премиальной доходностью."
    },
    "miner_6": {
        "name": "🏆 Miner God-Like",
        "speed": 0.80,
        "stars": 999,
        "rub": 1600.0,
        "gram": 12.5,
        "usdt": 17.0,
        "description": "Максимальный майнер в игре. Полное доминирование в топе!"
    },
}

# ==============================================================================
# 3. ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ БАЗЫ ДАННЫХ SQLite
# ==============================================================================

DB_PATH = "ultimate_mining.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    logger.info("Инициализация таблиц базы данных...")
    
    # Таблица пользователей
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0.0,
        safe_balance REAL DEFAULT 0.0,
        safe_capacity REAL DEFAULT 5.0,
        mining_speed REAL DEFAULT 0.001,
        last_mining_time TEXT,
        last_daily_bonus TEXT,
        invited_by INTEGER,
        referral_earned REAL DEFAULT 0.0,
        safe_upgrades_count INTEGER DEFAULT 0,
        miner_upgrades_count INTEGER DEFAULT 0,
        has_autocollect INTEGER DEFAULT 0,
        last_autocollect_time TEXT
    )
    """)

    # Таблица заявок на вывод
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        amount REAL,
        method TEXT,
        wallet TEXT,
        status TEXT DEFAULT 'pending'
    )
    """)

    # Таблица заявок на покупку товаров
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buy_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        miner_name TEXT,
        method TEXT,
        status TEXT DEFAULT 'pending'
    )
    """)

    # Таблица промокодов
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        reward REAL,
        uses_left INTEGER
    )
    """)

    # Таблица активаций промокодов
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS promo_activations (
        user_id INTEGER,
        code TEXT,
        PRIMARY KEY (user_id, code)
    )
    """)
    conn.commit()
    logger.info("База данных успешно инициализирована.")

def check_and_migrate_db():
    logger.info("Проверка и авто-миграция структуры колонок...")
    
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [col[1] for col in cursor.fetchall()]
    user_migrations = {
        "referral_earned": "REAL DEFAULT 0.0",
        "safe_upgrades_count": "INTEGER DEFAULT 0",
        "miner_upgrades_count": "INTEGER DEFAULT 0",
        "has_autocollect": "INTEGER DEFAULT 0",
        "last_autocollect_time": "TEXT"
    }
    for col_name, col_type in user_migrations.items():
        if col_name not in user_columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                conn.commit()
                logger.info(f"Добавлена колонка {col_name} в таблицу users")
            except Exception as e:
                logger.error(f"Ошибка миграции колонки {col_name}: {e}")

    cursor.execute("PRAGMA table_info(withdraw_requests)")
    withdraw_columns = [col[1] for col in cursor.fetchall()]
    if "username" not in withdraw_columns:
        try:
            cursor.execute("ALTER TABLE withdraw_requests ADD COLUMN username TEXT")
            conn.commit()
        except Exception:
            pass
    if "method" not in withdraw_columns:
        try:
            cursor.execute("ALTER TABLE withdraw_requests ADD COLUMN method TEXT")
            conn.commit()
        except Exception:
            pass

    cursor.execute("PRAGMA table_info(buy_requests)")
    buy_columns = [col[1] for col in cursor.fetchall()]
    if "username" not in buy_columns:
        try:
            cursor.execute("ALTER TABLE buy_requests ADD COLUMN username TEXT")
            conn.commit()
        except Exception:
            pass

init_db()
check_and_migrate_db()

# ==============================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ЛОГИКА ИГРЫ
# ==============================================================================

def check_sub_channel(user_id: int) -> bool:
    """Проверка подписки пользователя на обязательный канал."""
    try:
        member = bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
    except Exception as e:
        logger.warning(f"Ошибка проверки подписки для {user_id}: {e}")
    return False

def get_sub_keyboard():
    """Клавиатура с требованием подписаться."""
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"))
    kb.add(types.InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription"))
    return kb

def get_user(user_id: int, username: str = ""):
    """Получение или автоматическое создание профиля игрока."""
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, safe_balance, safe_capacity, mining_speed, last_mining_time, safe_upgrades_count, miner_upgrades_count, has_autocollect, last_autocollect_time) VALUES (?, ?, 0.0, 0.0, 5.0, 0.001, ?, 0, 0, 0, ?)",
            (user_id, username, now, now)
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        logger.info(f"Зарегистрирован новый пользователь: ID {user_id} (@{username})")
    else:
        if username and user[1] != username:
            cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()
    return user

def calculate_mining(user_id: int):
    """Математический просчет накопленных монет в сейфе и автосбора."""
    user = get_user(user_id)
    u_id, uname, balance, safe_balance, safe_capacity, mining_speed, last_time_str, _, invited_by, _, _, _, has_autocollect, last_autocollect_str = user

    if not last_time_str:
        last_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        last_time = datetime.now()

    now = datetime.now()
    seconds_passed = (now - last_time).total_seconds()

    if seconds_passed > 0 and safe_balance < safe_capacity:
        earned = seconds_passed * mining_speed
        
        if safe_balance + earned >= safe_capacity:
            earned = safe_capacity - safe_balance
            new_safe = safe_capacity
        else:
            new_safe = safe_balance + earned

        if invited_by and earned > 0:
            ref_bonus = earned * 0.10
            cursor.execute("UPDATE users SET balance = balance + ?, referral_earned = referral_earned + ? WHERE user_id = ?", (ref_bonus, ref_bonus, invited_by))

        new_time = now.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET safe_balance = ?, last_mining_time = ? WHERE user_id = ?", (new_safe, new_time, user_id))
        conn.commit()

    if has_autocollect == 1:
        if not last_autocollect_str:
            last_autocollect_str = now.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("UPDATE users SET last_autocollect_time = ? WHERE user_id = ?", (last_autocollect_str, user_id))
            conn.commit()

        try:
            last_auto_time = datetime.strptime(last_autocollect_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            last_auto_time = now

        if (now - last_auto_time).total_seconds() >= 3600:
            cursor.execute("SELECT safe_balance FROM users WHERE user_id = ?", (user_id,))
            current_safe = cursor.fetchone()[0]
            
            if current_safe > 0:
                new_balance = balance + current_safe
                new_auto_time = now.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE users SET balance = ?, safe_balance = 0.0, last_autocollect_time = ? WHERE user_id = ?", (new_balance, new_auto_time, user_id))
                conn.commit()
            else:
                new_auto_time = now.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE users SET last_autocollect_time = ? WHERE user_id = ?", (new_auto_time, user_id))
                conn.commit()

# ==============================================================================
# 5. ГЕНЕРАЦИЯ КЛАВИАТУР
# ==============================================================================

def main_menu_kb(is_admin: bool):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton(text="🏭 Сейф и Фарминг", callback_data="my_safe"))
    kb.add(
        types.InlineKeyboardButton(text="🛒 Магазин", callback_data="shop_main"),
        types.InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily")
    )
    kb.add(
        types.InlineKeyboardButton(text="🎮 Мини-игры", callback_data="menu_minigames"),
        types.InlineKeyboardButton(text="🎟 Промокод", callback_data="promo")
    )
    kb.add(
        types.InlineKeyboardButton(text="👥 Рефералы", callback_data="referral"),
        types.InlineKeyboardButton(text="🏆 Топ майнеров", callback_data="top")
    )
    kb.add(
        types.InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw"),
        types.InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")
    )
    if is_admin:
        kb.add(types.InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin"))
    return kb

def back_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu"))
    return kb

# ==============================================================================
# 6. ОБРАБОТЧИКИ КОМАНД И CALLBACK_QUERY
# ==============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    user_states.pop(user_id, None)

    if not check_sub_channel(user_id):
        bot.send_message(
            user_id,
            f"❌ <b>Для использования бота необходима подписка на наш канал!</b>\n\n"
            f"Подпишись на {CHANNEL_USERNAME}, а затем нажми кнопку «Проверить подписку».",
            reply_markup=get_sub_keyboard()
        )
        return

    args = message.text.split()
    user = get_user(user_id, username)

    if len(args) > 1 and not user[8]:
        try:
            referrer_id = int(args[1])
            if referrer_id != user_id:
                cursor.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (referrer_id, user_id))
                conn.commit()
                logger.info(f"Пользователь {user_id} стал рефералом {referrer_id}")
        except ValueError:
            pass

    is_admin = (user_id == ADMIN_ID)
    text = (
        f"🚀 <b>Добро пожаловать в CoinFarm Empire!</b>\n\n"
        f"Следи за сейфом, прокачивай майнеры, играй в мини-игры и выводи реальные средства!"
    )
    bot.send_message(user_id, text, reply_markup=main_menu_kb(is_admin))

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def cb_check_subscription(callback):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name

    if check_sub_channel(user_id):
        try:
            bot.delete_message(callback.message.chat.id, callback.message.message_id)
        except Exception:
            pass
        user = get_user(user_id, username)
        is_admin = (user_id == ADMIN_ID)
        text = (
            f"✅ <b>Подписка подтверждена! Добро пожаловать!</b>\n\n"
            f"🪙 Основной баланс: <b>{user[2]:.2f} монет</b>\n"
            f"💼 В сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
            f"⚡ Скорость: <b>{user[5]:.4f} монеты/сек</b>"
        )
        bot.send_message(user_id, text, reply_markup=main_menu_kb(is_admin))
    else:
        bot.answer_callback_query(callback.id, "❌ Вы всё еще не подписаны на канал!", show_alert=True)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(callback):
    user_id = callback.from_user.id
    if not check_sub_channel(user_id):
        bot.answer_callback_query(callback.id, "❌ Сначала подпишитесь на канал @CoinFarmEmpire!", show_alert=True)
        return

    data = callback.data

    if data == "menu":
        user_states.pop(user_id, None)
        user = get_user(user_id)
        calculate_mining(user_id)
        is_admin = (user_id == ADMIN_ID)
        text = (
            f"🏠 <b>Главное меню</b>\n\n"
            f"🪙 Основной баланс: <b>{user[2]:.2f} монет</b>\n"
            f"💼 В сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
            f"⚡ Скорость: <b>{user[5]:.4f} монеты/сек</b>"
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=main_menu_kb(is_admin))

    elif data == "info":
        text = (
            "ℹ️ <b>Информация о боте и правила</b>\n\n"
            "🤖 <b>Что делает бот?</b>\n"
            "Это экономический симулятор майнинга криптомонет. Вы собираете монеты из сейфа, прокачиваете оборудование, приглашаете друзей и участвуете в мини-играх.\n\n"
            "🛒 <b>Как покупать улучшения и майнеры?</b>\n"
            "Вы можете улучшать сейф, приобретать автосбор и скорость за игровые монеты или рубли в магазине.\n\n"
            "💸 <b>Как работает вывод?</b>\n"
            "Вы можете создать заявку на вывод от 2500 монет, указав удобный метод."
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "my_safe":
        calculate_mining(user_id)
        user = get_user(user_id)
        safe_full = (user[3] >= user[4])
        status_text = "🔴 <b>Сейф заполнен! Майнинг приостановлен до сбора!</b>" if safe_full else "🟢 <b>Сейф активно наполняется...</b>"
        auto_status = "✅ <b>Автосбор активен</b>" if user[12] == 1 else "❌ <b>Автосбор не куплен</b>"
        text = (
            f"🏭 <b>Твой Сейф и Майнинг</b>\n\n{status_text}\n{auto_status}\n\n"
            f"💼 Накоплено в сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
            f"⚡ Текущая скорость: <b>{user[5]:.4f} монет/сек</b>"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(text="📥 Забрать монеты в кошелек", callback_data="claim_safe"))
        kb.add(types.InlineKeyboardButton(text="🔄 Обновить", callback_data="my_safe"))
        kb.add(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu"))
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data == "claim_safe":
        calculate_mining(user_id)
        user = get_user(user_id)
        safe_amt = user[3]
        if safe_amt <= 0:
            bot.answer_callback_query(callback.id, "❌ В сейфе пока пусто!", show_alert=True)
            return
        cursor.execute(
            "UPDATE users SET balance = balance + ?, safe_balance = 0.0, last_mining_time = ? WHERE user_id = ?",
            (safe_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        conn.commit()
        bot.answer_callback_query(callback.id, f"✅ Успешно собрано {safe_amt:.2f} монет!", show_alert=True)
        handle_callbacks(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data="my_safe"))

    elif data == "shop_main":
        user = get_user(user_id)
        text = f"🛒 <b>Магазин улучшений</b>\n🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\nВыбери раздел ниже 👇"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text="💼 1. Улучшение Сейфа и Автосбор", callback_data="shop_safe"),
            types.InlineKeyboardButton(text="⚡ 2. Прокачка Майнера (Скорость)", callback_data="shop_upgrade"),
            types.InlineKeyboardButton(text="💎 3. Эксклюзивные Майнеры", callback_data="shop_exclusive"),
            types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data == "shop_safe":
        user = get_user(user_id)
        upgrades_count = user[10]
        has_autocollect = user[12]
        next_cost = 2 if upgrades_count == 0 else (5 if upgrades_count == 1 else 7)
        next_boost = 2.0 if upgrades_count == 0 else (3.0 if upgrades_count == 1 else 5.0)
        autocollect_text = "✅ Автосбор уже куплен" if has_autocollect == 1 else "🛒 Купить Автосбор (449 руб)"

        text = (
            f"💼 <b>Улучшение сейфа и Автосбор</b>\n🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
            f"Вместимость: <b>{user[4]:.1f} монет</b>\nСтоимость апгрейда: <b>{next_cost} монет</b> ➡️ +{next_boost:.0f}"
        )
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text=f"⚡ Увеличить сейф (+{next_boost:.0f} за {next_cost} монет)", callback_data="upgrade_safe_action"),
            types.InlineKeyboardButton(text=autocollect_text, callback_data="buy_autocollect_menu"),
            types.InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop_main")
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data == "upgrade_safe_action":
        user = get_user(user_id)
        upgrades_count = user[10]
        next_cost = 2 if upgrades_count == 0 else (5 if upgrades_count == 1 else 7)
        next_boost = 2.0 if upgrades_count == 0 else (3.0 if upgrades_count == 1 else 5.0)

        if user[2] < next_cost:
            bot.answer_callback_query(callback.id, f"❌ Недостаточно монет (нужно {next_cost})!", show_alert=True)
            return

        cursor.execute(
            "UPDATE users SET balance = balance - ?, safe_capacity = safe_capacity + ?, safe_upgrades_count = safe_upgrades_count + 1 WHERE user_id = ?",
            (next_cost, next_boost, user_id)
        )
        conn.commit()
        bot.answer_callback_query(callback.id, f"🎉 Сейф увеличен на +{next_boost:.0f}!", show_alert=True)
        handle_callbacks(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data="shop_safe"))

    elif data == "buy_autocollect_menu":
        user = get_user(user_id)
        if user[12] == 1:
            bot.answer_callback_query(callback.id, "✅ Автосбор уже приобретен!", show_alert=True)
            return
        username = callback.from_user.username or callback.from_user.first_name
        cursor.execute(
            "INSERT INTO buy_requests (user_id, username, miner_name, method, status) VALUES (?, ?, '🤖 Автосбор сейфа', 'Рубли (Т-Банк)', 'pending')",
            (user_id, username)
        )
        conn.commit()
        try:
            bot.send_message(
                ADMIN_ID,
                f"🛒 <b>Новая заявка на покупку Автосбора!</b>\n👤 Игрок: @{username} (ID: <code>{user_id}</code>)\n💳 Сумма: <b>449 руб.</b>"
            )
        except Exception:
            pass
        text = f"🤖 <b>Покупка: Автосбор для сейфа</b>\n\nРеквизиты Т-Банк: <code>{ADMIN_CARD}</code>\nСумма: <b>449 руб.</b>\n\nПереведи сумму и заявка отправится админу."
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "shop_upgrade":
        user = get_user(user_id)
        upgrades_count = user[11]
        next_cost = (upgrades_count + 1) * 5
        next_boost = (upgrades_count + 1) * 0.002
        text = (
            f"⚡ <b>Прокачка скорости майнера</b>\n🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
            f"Скорость: <b>{user[5]:.4f} монет/сек</b>\nСтоимость: <b>{next_cost} монет</b> ➡️ +{next_boost:.3f}/сек"
        )
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text=f"🚀 Улучшить скорость (+{next_boost:.3f})", callback_data="upgrade_miner_action"),
            types.InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop_main")
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data == "upgrade_miner_action":
        user = get_user(user_id)
        upgrades_count = user[11]
        next_cost = (upgrades_count + 1) * 5
        next_boost = (upgrades_count + 1) * 0.002

        if user[2] < next_cost:
            bot.answer_callback_query(callback.id, f"❌ Недостаточно монет (нужно {next_cost})!", show_alert=True)
            return

        cursor.execute(
            "UPDATE users SET balance = balance - ?, mining_speed = mining_speed + ?, miner_upgrades_count = miner_upgrades_count + 1 WHERE user_id = ?",
            (next_cost, next_boost, user_id)
        )
        conn.commit()
        bot.answer_callback_query(callback.id, f"🎉 Скорость увеличена!", show_alert=True)
        handle_callbacks(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data="shop_upgrade"))

    elif data == "shop_exclusive":
        user = get_user(user_id)
        text = f"💎 <b>Эксклюзивные майнеры</b>\n🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\nВыбери майнер:"
        kb = types.InlineKeyboardMarkup(row_width=1)
        for m_key, m_val in EXCLUSIVE_MINERS.items():
            kb.add(types.InlineKeyboardButton(text=f"{m_val['name']} (+{m_val['speed']}/сек)", callback_data=f"buy_ex_{m_key}"))
        kb.add(types.InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop_main"))
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data.startswith("buy_ex_"):
        m_key = data.replace("buy_ex_", "")
        m_val = EXCLUSIVE_MINERS[m_key]
        text = f"💎 <b>Покупка: {m_val['name']}</b>\n📈 Доходность: <b>+{m_val['speed']} монет/сек</b>\n\nВыбери оплату:"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text=f"💵 Рубли ({m_val['rub']} руб)", callback_data=f"pay_rub_{m_key}"),
            types.InlineKeyboardButton(text=f"🪙 GRAM ({m_val['gram']} GRAM)", callback_data=f"pay_gram_{m_key}"),
            types.InlineKeyboardButton(text=f"💲 USDT ({m_val['usdt']} USDT)", callback_data=f"pay_usdt_{m_key}"),
            types.InlineKeyboardButton(text="🔙 К списку майнеров", callback_data="shop_exclusive")
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data.startswith("pay_rub_") or data.startswith("pay_gram_") or data.startswith("pay_usdt_"):
        parts = data.split("_")
        pay_type = parts[1]
        m_key = f"{parts[2]}_{parts[3]}"
        m_val = EXCLUSIVE_MINERS[m_key]
        username = callback.from_user.username or callback.from_user.first_name

        if pay_type == "rub":
            method_name = "Рубли (Т-Банк)"
            details = f"Реквизиты: <code>{ADMIN_CARD}</code>\nСумма: <b>{m_val['rub']} руб.</b>"
        elif pay_type == "gram":
            method_name = "GRAM"
            details = f"Адрес: <code>{ADMIN_WALLET}</code>\nСумма: <b>{m_val['gram']} GRAM</b>"
        else:
            method_name = "USDT (TRC20)"
            details = f"Адрес: <code>{ADMIN_WALLET}</code>\nСумма: <b>{m_val['usdt']} USDT</b>"

        cursor.execute(
            "INSERT INTO buy_requests (user_id, username, miner_name, method, status) VALUES (?, ?, ?, ?, 'pending')",
            (user_id, username, m_val['name'], method_name)
        )
        conn.commit()
        try:
            bot.send_message(
                ADMIN_ID,
                f"🛒 <b>Новая заявка на покупку!</b>\n👤 Игрок: @{username} (ID: <code>{user_id}</code>)\n💎 Майнер: <b>{m_val['name']}</b>"
            )
        except Exception:
            pass
        text = f"💳 <b>Оплата: {m_val['name']} ({method_name})</b>\n\n{details}\n\nПереведи точную сумму, заявка передана администратору."
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "daily":
        user = get_user(user_id)
        last_bonus_str = user[7]
        now = datetime.now()
        if last_bonus_str:
            try:
                last_bonus = datetime.strptime(last_bonus_str, "%Y-%m-%d %H:%M:%S")
                if now - last_bonus < timedelta(days=1):
                    bot.answer_callback_query(callback.id, "⏳ Бонус уже получен! Приходи завтра.", show_alert=True)
                    return
            except ValueError:
                pass
        bonus_amount = float(random.randint(1, 10))
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE users SET balance = balance + ?, last_daily_bonus = ? WHERE user_id = ?",
            (bonus_amount, now_str, user_id)
        )
        conn.commit()
        bot.answer_callback_query(callback.id, f"🎁 Бонус получен: +{bonus_amount:.0f} монет!", show_alert=True)
        handle_callbacks(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data="menu"))

    elif data == "menu_minigames":
        user_states.pop(user_id, None)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text="🪙 Орёл и Решка (Коэф x2)", callback_data="game_start_coin"),
            types.InlineKeyboardButton(text="🎯 Дартс (Коэф x1.8)", callback_data="game_start_darts"),
            types.InlineKeyboardButton(text="🏀 Баскетбол (Коэф x1.8)", callback_data="game_start_basket"),
            types.InlineKeyboardButton(text="⚽ Футбол (Коэф x1.8)", callback_data="game_start_football"),
            types.InlineKeyboardButton(text="🎰 Рулетка (777) (Коэф x3)", callback_data="game_start_roulette"),
            types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")
        )
        bot.edit_message_text("🎮 <b>Мини-игры</b>\n\nСтавка: от 1 до 100 монет", callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data.startswith("game_start_"):
        game_type = data.replace("game_start_", "")
        user_states[user_id] = {"action": "waiting_for_game_bet", "game_type": game_type}
        bot.edit_message_text("💰 <b>Сделай ставку</b>\n\nОтправь число от 1 до 100:", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "promo":
        user_states[user_id] = {"action": "waiting_for_promo"}
        bot.edit_message_text("🎟 <b>Активация промокода</b>\n\nОтправь текст промокода:", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "referral":
        user = get_user(user_id)
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        cursor.execute("SELECT COUNT(*) FROM users WHERE invited_by = ?", (user_id,))
        invited_count = cursor.fetchone()[0]
        text = (
            f"👥 <b>Реферальная система (10%)</b>\n\nПриглашай друзей и получай 10% пассива!\n\n"
            f"🔗 Ссылка:\n<code>{ref_link}</code>\n\nПриглашено: <b>{invited_count}</b>\nЗаработано: <b>{user[9]:.2f} монет</b>"
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "top":
        cursor.execute("SELECT username, mining_speed, balance FROM users ORDER BY balance DESC LIMIT 10")
        top_players = cursor.fetchall()
        text = "🏆 <b>Топ-10 Майнеров:</b>\n\n"
        for i, (uname, speed, bal) in enumerate(top_players, start=1):
            medal = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i}."))
            text += f"{medal} <b>{uname or 'Майнер'}</b> ({speed:.4f}/сек) — {bal:.1f} 🪙\n"
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "withdraw":
        user = get_user(user_id)
        if user[2] < 2500.0:
            bot.answer_callback_query(callback.id, f"❌ Мин. сумма для вывода: 2500 монет.", show_alert=True)
            return
        user_states[user_id] = {"action": "waiting_for_withdraw_amount"}
        bot.edit_message_text(f"💸 <b>Вывод средств</b>\n\nБаланс: {user[2]:.2f}\nВведи сумму вывода (от 2500):", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data.startswith("w_method_"):
        method = data.replace("w_method_", "")
        user_states[user_id]["withdraw_method"] = method
        user_states[user_id]["action"] = "waiting_for_withdraw_wallet"
        bot.edit_message_text(f"📥 Способ: <b>{method}</b>\n\nОтправь кошелек для выплаты:", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "admin":
        if user_id != ADMIN_ID:
            bot.answer_callback_query(callback.id, "❌ Доступ запрещен", show_alert=True)
            return
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'")
        pending_w = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM buy_requests WHERE status='pending'")
        pending_b = cursor.fetchone()[0]

        text = f"🛠 <b>Админ-панель</b>\n\nИгроков: {total_users}\nВыводов ждет: {pending_w}\nПокупок ждет: {pending_b}"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(text="📋 Заявки на вывод", callback_data="admin_withdraws"),
            types.InlineKeyboardButton(text="🛒 Заявки на покупку", callback_data="admin_buys"),
            types.InlineKeyboardButton(text="⚙️ Выдать/Забрать монеты", callback_data="admin_balance_manage"),
            types.InlineKeyboardButton(text="🎟 Управление промокодами", callback_data="admin_promo_manage"),
            types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")
        )
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data == "admin_withdraws":
        if user_id != ADMIN_ID:
            return
        cursor.execute("SELECT id, user_id, username, amount, method, wallet FROM withdraw_requests WHERE status='pending' LIMIT 5")
        requests = cursor.fetchall()
        if not requests:
            bot.answer_callback_query(callback.id, "✅ Нет активных заявок!", show_alert=True)
            return
        for req_id, u_id, uname, amount, method, wallet in requests:
            txt = f"💸 Вывод #{req_id}\nИгрок: @{uname} ({u_id})\nСумма: {amount}\nМетод: {method}\nКошелек: {wallet}"
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_ok_{req_id}"),
                types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay_no_{req_id}")
            )
            bot.send_message(user_id, txt, reply_markup=kb)
        bot.answer_callback_query(callback.id)

    elif data.startswith("pay_ok_"):
        if user_id != ADMIN_ID:
            return
        req_id = int(data.split("_")[2])
        cursor.execute("UPDATE withdraw_requests SET status = 'paid' WHERE id = ?", (req_id,))
        conn.commit()
        bot.edit_message_text(f"✅ Вывод #{req_id} закрыт.", callback.message.chat.id, callback.message.message_id)

    elif data.startswith("pay_no_"):
        if user_id != ADMIN_ID:
            return
        req_id = int(data.split("_")[2])
        cursor.execute("SELECT user_id, amount FROM withdraw_requests WHERE id = ?", (req_id,))
        res = cursor.fetchone()
        if res:
            u_id, amount = res
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, u_id))
            cursor.execute("UPDATE withdraw_requests SET status = 'rejected' WHERE id = ?", (req_id,))
            conn.commit()
            try:
                bot.send_message(u_id, f"❌ Заявка на вывод #{req_id} отклонена, средства ({amount}) возвращены.")
            except Exception:
                pass
        bot.edit_message_text(f"❌ Вывод #{req_id} отклонен.", callback.message.chat.id, callback.message.message_id)

    elif data == "admin_buys":
        if user_id != ADMIN_ID:
            return
        cursor.execute("SELECT id, user_id, username, miner_name, method FROM buy_requests WHERE status='pending' LIMIT 5")
        requests = cursor.fetchall()
        if not requests:
            bot.answer_callback_query(callback.id, "✅ Нет заявок на покупку!", show_alert=True)
            return
        for req_id, u_id, uname, m_name, method in requests:
            txt = f"🛒 Покупка #{req_id}\nИгрок: @{uname} ({u_id})\nТовар: {m_name}\nОплата: {method}"
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton(text="✅ Одобрить", callback_data=f"buy_ok_{req_id}"),
                types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"buy_no_{req_id}")
            )
            bot.send_message(user_id, txt, reply_markup=kb)
        bot.answer_callback_query(callback.id)

    elif data.startswith("buy_ok_"):
        if user_id != ADMIN_ID:
            return
        req_id = int(data.split("_")[2])
        cursor.execute("SELECT user_id, miner_name FROM buy_requests WHERE id = ?", (req_id,))
        res = cursor.fetchone()
        if res:
            u_id, m_name = res
            if "Автосбор" in m_name:
                cursor.execute("UPDATE users SET has_autocollect = 1 WHERE user_id = ?", (u_id,))
            else:
                speed_to_add = 0.05
                for m_k, m_v in EXCLUSIVE_MINERS.items():
                    if m_v["name"] == m_name:
                        speed_to_add = m_v["speed"]
                        break
                cursor.execute("UPDATE users SET mining_speed = mining_speed + ? WHERE user_id = ?", (speed_to_add, u_id))
            cursor.execute("UPDATE buy_requests SET status = 'approved' WHERE id = ?", (req_id,))
            conn.commit()
            try:
                bot.send_message(u_id, f"🎉 Администратор подтвердил покупку: <b>{m_name}</b>!")
            except Exception:
                pass
        bot.edit_message_text(f"✅ Покупка #{req_id} одобрена.", callback.message.chat.id, callback.message.message_id)

    elif data.startswith("buy_no_"):
        if user_id != ADMIN_ID:
            return
        req_id = int(data.split("_")[2])
        cursor.execute("UPDATE buy_requests SET status = 'rejected' WHERE id = ?", (req_id,))
        conn.commit()
        bot.edit_message_text(f"❌ Покупка #{req_id} отклонена.", callback.message.chat.id, callback.message.message_id)

    elif data == "admin_balance_manage":
        if user_id != ADMIN_ID:
            return
        user_states[user_id] = {"action": "waiting_for_balance_change"}
        bot.edit_message_text("⚙️ Введи данные: <code>ID СУММА</code> (например: <code>123456 +500</code>)", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

    elif data == "admin_promo_manage":
        if user_id != ADMIN_ID:
            return
        cursor.execute("SELECT code, reward, uses_left FROM promo_codes")
        promos = cursor.fetchall()
        text = "🎟 <b>Промокоды:</b>\n\n"
        kb = types.InlineKeyboardMarkup(row_width=1)
        if promos:
            for code, reward, uses in promos:
                text += f"• <b>{code}</b> | Награда: {reward} | Осталось: {uses}\n"
                kb.add(types.InlineKeyboardButton(text=f"🗑 Удалить {code}", callback_data=f"del_promo_{code}"))
        else:
            text += "<i>Нет промокодов.</i>\n"
        kb.add(types.InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_create_promo"))
        kb.add(types.InlineKeyboardButton(text="🔙 В админку", callback_data="admin"))
        bot.edit_message_text(text, callback.message.chat.id, callback.message.message_id, reply_markup=kb)

    elif data.startswith("del_promo_"):
        if user_id != ADMIN_ID:
            return
        code = data.replace("del_promo_", "")
        cursor.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        conn.commit()
        bot.answer_callback_query(callback.id, f"🗑 Удален {code}!", show_alert=True)
        handle_callbacks(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data="admin_promo_manage"))

    elif data == "admin_create_promo":
        if user_id != ADMIN_ID:
            return
        user_states[user_id] = {"action": "waiting_for_promo_create"}
        bot.edit_message_text("➕ Введи формат: <code>КОД НАГРАДА ЛИМИТ</code>", callback.message.chat.id, callback.message.message_id, reply_markup=back_kb())

# ==============================================================================
# 7. ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ
# ==============================================================================

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    if not check_sub_channel(user_id):
        bot.send_message(user_id, "❌ Подпишитесь на канал @CoinFarmEmpire!", reply_markup=get_sub_keyboard())
        return

    state = user_states.get(user_id)
    if not state:
        return

    action = state.get("action")

    if action == "waiting_for_game_bet":
        user_states.pop(user_id, None)
        try:
            bet = float(message.text.strip())
        except ValueError:
            bot.send_message(user_id, "❌ Введи число от 1 до 100!", reply_markup=back_kb())
            return

        if bet < 1 or bet > 100:
            bot.send_message(user_id, "❌ Ставка от 1 до 100 монет!", reply_markup=back_kb())
            return

        user = get_user(user_id)
        if user[2] < bet:
            bot.send_message(user_id, f"❌ Недостаточно средств ({user[2]:.2f} монет).", reply_markup=back_kb())
            return

        game_type = state.get("game_type")
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id))
        conn.commit()

        if game_type == "coin":
            if random.random() < 0.35:
                win = bet * 2.0
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                conn.commit()
                bot.send_message(user_id, f"🎉 <b>Победа!</b> +{win:.1f} монет (коэф x2)", reply_markup=back_kb())
            else:
                bot.send_message(user_id, f"😢 <b>Проигрыш!</b> Потеряно: {bet} монет", reply_markup=back_kb())

        elif game_type in ["darts", "basket", "football"]:
            emoji_map = {"darts": "🎯", "basket": "🏀", "football": "⚽"}
            bot.send_message(user_id, "🎲 Бросаем снаряд...")
            bot.send_dice(user_id, emoji=emoji_map[game_type])
            time.sleep(3)
            if random.random() < 0.35:
                win = bet * 1.8
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                conn.commit()
                bot.send_message(user_id, f"🎉 <b>Победа!</b> +{win:.1f} монет", reply_markup=back_kb())
            else:
                bot.send_message(user_id, f"😢 <b>Проигрыш!</b> Потеряно: {bet} монет", reply_markup=back_kb())

        elif game_type == "roulette":
            bot.send_message(user_id, "🎰 Крутим рулетку...")
            bot.send_dice(user_id, emoji="🎰")
            time.sleep(3.5)
            if random.random() < 0.08:
                win = bet * 3.0
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                conn.commit()
                bot.send_message(user_id, f"💎 JACKPOT! <b>777!</b> Выигрыш: +{win:.1f} монет", reply_markup=back_kb())
            else:
                bot.send_message(user_id, f"😢 <b>Мимо!</b> Потеряно: {bet} монет", reply_markup=back_kb())

    elif action == "waiting_for_promo":
        user_states.pop(user_id, None)
        code = message.text.strip().upper()
        cursor.execute("SELECT * FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, code))
        if cursor.fetchone():
            bot.send_message(user_id, "❌ Ты уже активировал этот промокод!", reply_markup=back_kb())
            return

        cursor.execute("SELECT reward, uses_left FROM promo_codes WHERE code = ?", (code,))
        promo = cursor.fetchone()
        if not promo or promo[1] <= 0:
            bot.send_message(user_id, "❌ Промокод недействителен или исчерпан.", reply_markup=back_kb())
            return

        reward, uses_left = promo
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
        cursor.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
        cursor.execute("INSERT INTO promo_activations (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.commit()
        bot.send_message(user_id, f"✅ Промокод активирован! Начислено: +{reward} монет.", reply_markup=back_kb())

    elif action == "waiting_for_withdraw_amount":
        try:
            amount = float(message.text.strip())
        except ValueError:
            bot.send_message(user_id, "❌ Введи корректное число!", reply_markup=back_kb())
            return

        user = get_user(user_id)
        if amount < 2500.0 or amount > user[2]:
            bot.send_message(user_id, "❌ Сумма должна быть от 2500 и не превышать твой баланс.", reply_markup=back_kb())
            return

        user_states[user_id]["withdraw_amount"] = amount
        user_states[user_id]["action"] = "waiting_for_withdraw_method"

        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton(text="💲 USDT", callback_data="w_method_USDT"),
            types.InlineKeyboardButton(text="🪙 GRAM", callback_data="w_method_GRAM"),
            types.InlineKeyboardButton(text="⭐ STARS", callback_data="w_method_STARS")
        )
        bot.send_message(user_id, "💳 Выбери способ вывода средств:", reply_markup=kb)

    elif action == "waiting_for_withdraw_wallet":
        username = message.from_user.username or message.from_user.first_name
        wallet = message.text.strip()
        amount = state.get("withdraw_amount")
        method = state.get("withdraw_method")
        user_states.pop(user_id, None)

        user = get_user(user_id)
        if user[2] < amount:
            bot.send_message(user_id, "❌ Ошибка: недостаточно средств.", reply_markup=back_kb())
            return

        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        cursor.execute(
            "INSERT INTO withdraw_requests (user_id, username, amount, method, wallet, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (user_id, username, amount, method, wallet)
        )
        conn.commit()
        try:
            bot.send_message(
                ADMIN_ID,
                f"💸 <b>Новая заявка на вывод!</b>\n👤 Игрок: @{username} ({user_id})\n💰 Сумма: {amount}\n💳 Метод: {method}\n📬 Кошелек: <code>{wallet}</code>"
            )
        except Exception:
            pass
        bot.send_message(user_id, "✅ <b>Заявка принята!</b> Администратор обработает её в ближайшее время.", reply_markup=back_kb())

    elif action == "waiting_for_balance_change" and user_id == ADMIN_ID:
        user_states.pop(user_id, None)
        try:
            parts = message.text.split()
            target_id = int(parts[0])
            diff = float(parts[1])
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
            res = cursor.fetchone()
            if not res:
                bot.send_message(user_id, "❌ Игрок не найден.")
                return
            new_bal = max(0.0, res[0] + diff)
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_id))
            conn.commit()
            bot.send_message(user_id, f"✅ Баланс игрока {target_id} изменен. Новый: {new_bal:.2f}")
        except Exception:
            bot.send_message(user_id, "❌ Ошибка формата! Используй: <code>ID +СУММА</code>")

    elif action == "waiting_for_promo_create" and user_id == ADMIN_ID:
        user_states.pop(user_id, None)
        try:
            parts = message.text.split()
            code = parts[0].strip().upper()
            reward = float(parts[1])
            uses = int(parts[2])
            cursor.execute("INSERT OR REPLACE INTO promo_codes (code, reward, uses_left) VALUES (?, ?, ?)", (code, reward, uses))
            conn.commit()
            bot.send_message(user_id, f"✅ Промокод <b>{code}</b> на {reward} монет создан!")
        except Exception:
            bot.send_message(user_id, "❌ Ошибка формата! Используй: <code>КОД НАГРАДА ЛИМИТ</code>")

# ==============================================================================
# 8. ДЕКЛАРАЦИЯ ДОПОЛНИТЕЛЬНЫХ СЛУЖЕБНЫХ ФУНКЦИЙ И МОДУЛЕЙ
# ==============================================================================

def print_system_info():
    """Вывод подробной служебной информации в консоль при запуске."""
    logger.info("==============================================")
    logger.info("   CoinFarm Empire Server Engine Launched     ")
    logger.info("   Bot Framework: pyTelegramBotAPI (Telebot)  ")
    logger.info("   Database Engine: SQLite3 (Local Sync)      ")
    logger.info("==============================================")

def background_mining_loop():
    """Фоновый поток для расчета пассивного дохода каждые 5 секунд."""
    logger.info("Запуск фонового потока авто-майнинга...")
    while True:
        time.sleep(5)
        try:
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            for (u_id,) in users:
                calculate_mining(u_id)
        except Exception as e:
            logger.error(f"Ошибка в фоновом цикле майнинга: {e}")

# ==============================================================================
# 9. ТОЧКА ВХОДА И ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    print_system_info()
    
    # Запуск фонового процесса для расчета фермы
    mining_thread = threading.Thread(target=background_mining_loop, daemon=True)
    mining_thread.start()
    
    logger.info("Запуск опроса серверов Telegram (Polling)...")
    try:
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        logger.critical(f"Критическая ошибка работы бота: {e}")
