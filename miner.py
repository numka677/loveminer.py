import asyncio
from datetime import datetime, timedelta
import random
import sqlite3
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
)

TOKEN = "8320216944:AAE2PhFNEIu6Yg1nxppjIRQOt1Z2noOX-Jc"
ADMIN_ID = 5095702210  # Твой Telegram ID
ADMIN_CARD = "2200 7012 3674 6712 (Т-Банк)"
ADMIN_WALLET = "UQCEys8Frn_276y6a2p15ZbPJEjsKLhotfv9gDARyIoIOD1G"
CHANNEL_USERNAME = "@CoinFarmEmpire"  # Юзернейм твоего канала

bot = Bot(token=TOKEN)
router = Router()
dp = Dispatcher()

# --- БАЗА ДАННЫХ И АВТО-МИГРАЦИЯ КОЛОНОК ---
conn = sqlite3.connect("ultimate_mining.db", check_same_thread=False)
cursor = conn.cursor()

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    reward REAL,
    uses_left INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS promo_activations (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY (user_id, code)
)
""")
conn.commit()


def check_and_migrate_db():
  cursor.execute("PRAGMA table_info(users)")
  user_columns = [col[1] for col in cursor.fetchall()]
  user_migrations = {
      "referral_earned": "REAL DEFAULT 0.0",
      "safe_upgrades_count": "INTEGER DEFAULT 0",
      "miner_upgrades_count": "INTEGER DEFAULT 0",
      "has_autocollect": "INTEGER DEFAULT 0",
      "last_autocollect_time": "TEXT",
  }
  for col_name, col_type in user_migrations.items():
    if col_name not in user_columns:
      try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
        conn.commit()
      except Exception:
        pass

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


check_and_migrate_db()


# --- ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ---
async def check_sub_channel(user_id: int) -> bool:
  try:
    member = await bot.get_chat_member(
        chat_id=CHANNEL_USERNAME, user_id=user_id
    )
    if member.status in ["creator", "administrator", "member"]:
      return True
  except Exception:
    pass
  return False


def get_sub_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📢 Подписаться на канал",
                  url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔄 Проверить подписку", callback_data="check_subscription"
              )
          ],
      ]
  )


def get_user(user_id, username=""):
  cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
  user = cursor.fetchone()
  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  if not user:
    cursor.execute(
        "INSERT INTO users (user_id, username, balance, safe_balance,"
        " safe_capacity, mining_speed, last_mining_time, safe_upgrades_count,"
        " miner_upgrades_count, has_autocollect, last_autocollect_time) VALUES"
        " (?, ?, 0.0, 0.0, 5.0, 0.001, ?, 0, 0, 0, ?)",
        (user_id, username, now, now),
    )
    conn.commit()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
  else:
    if username and user[1] != username:
      cursor.execute(
          "UPDATE users SET username = ? WHERE user_id = ?", (username, user_id)
      )
      conn.commit()
  return user


def calculate_mining(user_id):
  user = get_user(user_id)
  (
      u_id,
      uname,
      balance,
      safe_balance,
      safe_capacity,
      mining_speed,
      last_time_str,
      _,
      invited_by,
      _,
      _,
      _,
      has_autocollect,
      last_autocollect_str,
  ) = user

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
      cursor.execute(
          "UPDATE users SET balance = balance + ?, referral_earned ="
          " referral_earned + ? WHERE user_id = ?",
          (ref_bonus, ref_bonus, invited_by),
      )

    new_time = now.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE users SET safe_balance = ?, last_mining_time = ? WHERE user_id ="
        " ?",
        (new_safe, new_time, user_id),
    )
    conn.commit()

  if has_autocollect == 1:
    if not last_autocollect_str:
      last_autocollect_str = now.strftime("%Y-%m-%d %H:%M:%S")
      cursor.execute(
          "UPDATE users SET last_autocollect_time = ? WHERE user_id = ?",
          (last_autocollect_str, user_id),
      )
      conn.commit()

    try:
      last_auto_time = datetime.strptime(
          last_autocollect_str, "%Y-%m-%d %H:%M:%S"
      )
    except ValueError:
      last_auto_time = now

    if (now - last_auto_time).total_seconds() >= 3600:
      cursor.execute("SELECT safe_balance FROM users WHERE user_id = ?", (user_id,))
      current_safe = cursor.fetchone()[0]

      if current_safe > 0:
        new_balance = balance + current_safe
        new_auto_time = now.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE users SET balance = ?, safe_balance = 0.0,"
            " last_autocollect_time = ? WHERE user_id = ?",
            (new_balance, new_auto_time, user_id),
        )
        conn.commit()
      else:
        new_auto_time = now.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE users SET last_autocollect_time = ? WHERE user_id = ?",
            (new_auto_time, user_id),
        )
        conn.commit()


# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
  waiting_for_balance_change = State()
  waiting_for_promo_create = State()


class UserStates(StatesGroup):
  waiting_for_withdraw_amount = State()
  waiting_for_withdraw_method = State()
  waiting_for_withdraw_wallet = State()
  waiting_for_promo = State()
  waiting_for_game_bet = State()
  waiting_for_game_choice = State()


# --- ЭКСКЛЮЗИВНЫЕ МАЙНЕРЫ ---
EXCLUSIVE_MINERS = {
    "miner_1": {
        "name": "⚡ Miner Usual",
        "speed": 0.05,
        "stars": 99,
        "rub": 150.0,
        "gram": 1.2,
        "usdt": 1.6,
    },
    "miner_2": {
        "name": "🔥 Miner Turbo",
        "speed": 0.10,
        "stars": 199,
        "rub": 300.0,
        "gram": 2.4,
        "usdt": 3.2,
    },
    "miner_3": {
        "name": "💎 Miner Monster",
        "speed": 0.20,
        "stars": 349,
        "rub": 550.0,
        "gram": 4.3,
        "usdt": 5.8,
    },
    "miner_4": {
        "name": "🚀 Miner Quantum",
        "speed": 0.35,
        "stars": 499,
        "rub": 800.0,
        "gram": 6.2,
        "usdt": 8.5,
    },
    "miner_5": {
        "name": "👑 Miner Cyber",
        "speed": 0.50,
        "stars": 749,
        "rub": 1200.0,
        "gram": 9.4,
        "usdt": 12.8,
    },
    "miner_6": {
        "name": "🏆 Miner God-Like",
        "speed": 0.80,
        "stars": 999,
        "rub": 1600.0,
        "gram": 12.5,
        "usdt": 17.0,
    },
}


# --- КЛАВИАТУРЫ ---
def main_menu_kb(is_admin: bool):
  kb = [
      [InlineKeyboardButton(text="🏭 Сейф и Фарминг", callback_data="my_safe")],
      [
          InlineKeyboardButton(text="🛒 Магазин", callback_data="shop_main"),
          InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily"),
      ],
      [
          InlineKeyboardButton(text="🎮 Мини-игры", callback_data="menu_minigames"),
          InlineKeyboardButton(text="🎟 Промокод", callback_data="promo"),
      ],
      [
          InlineKeyboardButton(text="👥 Рефералы", callback_data="referral"),
          InlineKeyboardButton(text="🏆 Топ майнеров", callback_data="top"),
      ],
      [
          InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw"),
          InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"),
      ],
  ]
  if is_admin:
    kb.append(
        [InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin")]
    )
  return InlineKeyboardMarkup(inline_keyboard=kb)


def back_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")]
      ]
  )


# --- СТАРТ И ПРОВЕРКА ПОДПИСКИ ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
  await state.clear()
  user_id = message.from_user.id
  username = message.from_user.username or message.from_user.first_name

  # Проверка подписки
  if not await check_sub_channel(user_id):
    await message.answer(
        "❌ <b>Для использования бота необходима подписка на наш канал!</b>\n\n"
        f"Подпишись на {CHANNEL_USERNAME}, а затем нажми кнопку «Проверить подписку».",
        reply_markup=get_sub_keyboard(),
        parse_mode="HTML",
    )
    return

  args = message.text.split()
  user = get_user(user_id, username)

  if len(args) > 1 and not user[8]:
    try:
      referrer_id = int(args[1])
      if referrer_id != user_id:
        cursor.execute(
            "UPDATE users SET invited_by = ? WHERE user_id = ?",
            (referrer_id, user_id),
        )
        conn.commit()
    except ValueError:
      pass

  is_admin = user_id == ADMIN_ID
  text = (
      f"🚀 <b>Добро пожаловать в CoinFarm Empire!</b>\n\n"
      "Следи за сейфом, прокачивай майнеры, играй в мини-игры и выводи реальные средства!"
  )
  await message.answer(
      text, reply_markup=main_menu_kb(is_admin), parse_mode="HTML"
  )


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery, state: FSMContext):
  user_id = callback.from_user.id
  username = callback.from_user.username or callback.from_user.first_name

  if await check_sub_channel(user_id):
    await callback.message.delete()
    user = get_user(user_id, username)
    is_admin = user_id == ADMIN_ID
    text = (
        f"✅ <b>Подписка подтверждена! Добро пожаловать!</b>\n\n"
        f"🪙 Основной баланс: <b>{user[2]:.2f} монет</b>\n"
        f"💼 В сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
        f"⚡ Скорость: <b>{user[5]:.4f} монеты/сек</b>"
    )
    await callback.message.answer(
        text, reply_markup=main_menu_kb(is_admin), parse_mode="HTML"
    )
  else:
    await callback.answer(
        "❌ Вы всё еще не подписаны на канал!", show_alert=True
    )


# --- ГЛОБАЛЬНЫЙ МИДДЛВАРЬ/ДЕКОРАТОР ДЛЯ КНОПОК И СООБЩЕНИЙ ---
@router.callback_query(F.data != "check_subscription")
async def check_sub_before_callback(callback: CallbackQuery, state: FSMContext):
  user_id = callback.from_user.id
  if not await check_sub_channel(user_id):
    await callback.answer(
        "❌ Сначала подпишитесь на канал @CoinFarmEmpire!", show_alert=True
    )
    try:
      await callback.message.edit_text(
          "❌ <b>Для использования бота необходима подписка на наш канал!</b>\n\n"
          f"Подпишись на {CHANNEL_USERNAME}, а затем нажми кнопку «Проверить подписку».",
          reply_markup=get_sub_keyboard(),
          parse_mode="HTML",
      )
    except Exception:
      pass
    return

  # Если подписан, обрабатываем стандартные колбэки
  if callback.data == "menu":
    await cb_menu(callback, state)
  elif callback.data == "my_safe":
    await cb_my_safe(callback)
  elif callback.data == "claim_safe":
    await cb_claim_safe(callback)
  elif callback.data == "shop_main":
    await cb_shop_main(callback)
  elif callback.data == "shop_safe":
    await cb_shop_safe(callback)
  elif callback.data == "upgrade_safe_action":
    await cb_upgrade_safe(callback)
  elif callback.data == "buy_autocollect_menu":
    await cb_buy_autocollect_menu(callback)
  elif callback.data == "shop_upgrade":
    await cb_shop_upgrade(callback)
  elif callback.data == "upgrade_miner_action":
    await cb_upgrade_miner(callback)
  elif callback.data == "shop_exclusive":
    await cb_shop_exclusive(callback)
  elif callback.data.startswith("buy_ex_"):
    await cb_buy_exclusive(callback)
  elif callback.data.startswith("pay_stars_"):
    await pay_with_stars(callback)
  elif (
      callback.data.startswith("pay_rub_")
      or callback.data.startswith("pay_gram_")
      or callback.data.startswith("pay_usdt_")
  ):
    await pay_manual(callback)
  elif callback.data == "daily":
    await cb_daily(callback)
  elif callback.data == "menu_minigames":
    await open_minigames(callback, state)
  elif callback.data.startswith("game_start_"):
    await ask_game_bet(callback, state)
  elif callback.data == "promo":
    await cb_promo(callback, state)
  elif callback.data == "referral":
    await cb_referral(callback)
  elif callback.data == "top":
    await cb_top(callback)
  elif callback.data == "withdraw":
    await cb_withdraw(callback, state)
  elif callback.data.startswith("w_method_"):
    await cb_withdraw_method(callback, state)
  elif callback.data == "admin":
    await cb_admin(callback)
  elif callback.data == "admin_withdraws":
    await cb_admin_withdraws(callback)
  elif callback.data.startswith("pay_ok_"):
    await cb_pay_ok(callback)
  elif callback.data.startswith("pay_no_"):
    await cb_pay_no(callback)
  elif callback.data == "admin_buys":
    await cb_admin_buys(callback)
  elif callback.data.startswith("buy_ok_"):
    await cb_buy_ok(callback)
  elif callback.data.startswith("buy_no_"):
    await cb_buy_no(callback)
  elif callback.data == "admin_balance_manage":
    await cb_admin_balance_manage(callback, state)
  elif callback.data == "admin_promo_manage":
    await cb_admin_promo_manage(callback)
  elif callback.data.startswith("del_promo_"):
    await cb_del_promo(callback)
  elif callback.data == "admin_create_promo":
    await cb_admin_create_promo(callback, state)
  elif callback.data == "info":
    await cb_info(callback)


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
  if state:
    await state.clear()
  user_id = callback.from_user.id
  username = callback.from_user.username or callback.from_user.first_name
  get_user(user_id, username)
  calculate_mining(user_id)
  is_admin = user_id == ADMIN_ID
  user = get_user(user_id)

  text = (
      f"🏠 <b>Главное меню</b>\n\n"
      f"🪙 Основной баланс: <b>{user[2]:.2f} монет</b>\n"
      f"💼 В сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
      f"⚡ Скорость: <b>{user[5]:.4f} монеты/сек</b>"
  )
  await callback.message.edit_text(
      text, reply_markup=main_menu_kb(is_admin), parse_mode="HTML"
  )


@router.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
  text = (
      "ℹ️ <b>Информация о боте и правила</b>\n\n"
      "🤖 <b>Что делает бот?</b>\n"
      "Это экономический симулятор майнинга криптомонет. Вы собираете монеты из сейфа, прокачиваете оборудование, приглашаете друзей и участвуете в мини-играх.\n\n"
      "🛒 <b>Как покупать улучшения и майнеры?</b>\n"
      "Вы можете улучшать сейф, приобретать автосбор и скорость за игровые монеты или рубли в магазине.\n\n"
      "💸 <b>Как работает вывод?</b>\n"
      "Вы можете создать заявку на вывод от 2500 монет, указав удобный метод."
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# --- СЕЙФ И СБОР МОНЕТ ---
@router.callback_query(F.data == "my_safe")
async def cb_my_safe(callback: CallbackQuery):
  user_id = callback.from_user.id
  calculate_mining(user_id)
  user = get_user(user_id)

  safe_full = user[3] >= user[4]
  status_text = (
      "🔴 <b>Сейф заполнен! Майнинг приостановлен до сбора!</b>"
      if safe_full
      else "🟢 <b>Сейф активно наполняется...</b>"
  )
  auto_status = (
      "✅ <b>Автосбор активен</b> (автоматически собирает монеты каждый час)"
      if user[12] == 1
      else "❌ <b>Автосбор не куплен</b>"
  )

  text = (
      f"🏭 <b>Твой Сейф и Майнинг</b>\n\n"
      f"{status_text}\n"
      f"{auto_status}\n\n"
      f"💼 Накоплено в сейфе: <b>{user[3]:.2f} / {user[4]:.1f} монет</b>\n"
      f"⚡ Текущая скорость: <b>{user[5]:.4f} монет/сек</b>"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📥 Забрать монеты в кошелек", callback_data="claim_safe"
              )
          ],
          [InlineKeyboardButton(text="🔄 Обновить", callback_data="my_safe")],
          [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "claim_safe")
async def cb_claim_safe(callback: CallbackQuery):
  user_id = callback.from_user.id
  calculate_mining(user_id)
  user = get_user(user_id)
  safe_amt = user[3]

  if safe_amt <= 0:
    await callback.answer("❌ В сейфе пока пусто!", show_alert=True)
    return

  cursor.execute(
      "UPDATE users SET balance = balance + ?, safe_balance = 0.0, last_mining_time ="
      " ? WHERE user_id = ?",
      (safe_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
  )
  conn.commit()

  await callback.answer(
      f"✅ Успешно собрано {safe_amt:.2f} монет на баланс!", show_alert=True
  )
  await cb_my_safe(callback)


# --- МАГАЗИН ---
@router.callback_query(F.data == "shop_main")
async def cb_shop_main(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  text = (
      f"🛒 <b>Магазин улучшений</b>\n"
      f"🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
      "Выбери интересующий тебя раздел ниже 👇"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="💼 1. Улучшение Сейфа и Автосбор",
                  callback_data="shop_safe",
              )
          ],
          [
              InlineKeyboardButton(
                  text="⚡ 2. Прокачка Майнера (Скорость)",
                  callback_data="shop_upgrade",
              )
          ],
          [
              InlineKeyboardButton(
                  text="💎 3. Эксклюзивные Майнеры",
                  callback_data="shop_exclusive",
              )
          ],
          [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "shop_safe")
async def cb_shop_safe(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  upgrades_count = user[10]
  has_autocollect = user[12]

  if upgrades_count == 0:
    next_cost = 2
    next_boost = 2.0
  elif upgrades_count == 1:
    next_cost = 5
    next_boost = 3.0
  else:
    next_cost = 7
    next_boost = 5.0

  autocollect_text = (
      "✅ Автосбор уже куплен"
      if has_autocollect == 1
      else "🛒 Купить Автосбор (449 руб)"
  )

  text = (
      f"💼 <b>Улучшение сейфа и Автосбор</b>\n"
      f"🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
      f"Текущая вместимость: <b>{user[4]:.1f} монет</b>\n"
      f"Стоимость апгрейда сейфа: <b>{next_cost} монет</b> ➡️ Дает:"
      f" <b>+{next_boost:.0f} к вместимости</b>\n\n"
      "🤖 <b>Автосбор:</b> если он есть у пользователя, то автосбор будет каждый"
      " час собирать то, что лежит в сейфе."
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text=(
                      f"⚡ Увеличить сейф (+{next_boost:.0f} за"
                      f" {next_cost} монет)"
                  ),
                  callback_data="upgrade_safe_action",
              )
          ],
          [
              InlineKeyboardButton(
                  text=autocollect_text, callback_data="buy_autocollect_menu"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 Назад в магазин", callback_data="shop_main"
              )
          ],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "upgrade_safe_action")
async def cb_upgrade_safe(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  upgrades_count = user[10]

  if upgrades_count == 0:
    next_cost = 2
    next_boost = 2.0
  elif upgrades_count == 1:
    next_cost = 5
    next_boost = 3.0
  else:
    next_cost = 7
    next_boost = 5.0

  if user[2] < next_cost:
    await callback.answer(
        f"❌ Недостаточно монет на балансе (нужно {next_cost})!", show_alert=True
    )
    return

  cursor.execute(
      "UPDATE users SET balance = balance - ?, safe_capacity = safe_capacity +"
      " ?, safe_upgrades_count = safe_upgrades_count + 1 WHERE user_id = ?",
      (next_cost, next_boost, user_id),
  )
  conn.commit()
  await callback.answer(
      f"🎉 Сейф успешно увеличен на +{next_boost:.0f} вместимости!",
      show_alert=True,
  )
  await cb_shop_safe(callback)


@router.callback_query(F.data == "buy_autocollect_menu")
async def cb_buy_autocollect_menu(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  if user[12] == 1:
    await callback.answer("✅ Автосбор уже приобретен!", show_alert=True)
    return

  username = callback.from_user.username or callback.from_user.first_name

  cursor.execute(
      "INSERT INTO buy_requests (user_id, username, miner_name, method, status)"
      " VALUES (?, ?, '🤖 Автосбор сейфа', 'Рубли (Т-Банк)', 'pending')",
      (user_id, username),
  )
  conn.commit()

  try:
    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>Новая заявка на покупку Автосбора!</b>\n"
        f"👤 Игрок: @{username} (ID: <code>{user_id}</code>)\n"
        f"💳 Сумма: <b>449 руб. (Т-Банк)</b>",
        parse_mode="HTML",
    )
  except Exception:
    pass

  details = (
      f"Реквизиты Т-Банк: <code>{ADMIN_CARD}</code>\nСумма: <b>449 руб.</b>"
  )
  text = (
      f"🤖 <b>Покупка: Автосбор для сейфа</b>\n\n"
      f"{details}\n\n"
      "1. Переведи точную сумму (449 руб.) по реквизитам выше.\n"
      "2. Заявка отправлена администратору. После проверки автосбор будет"
      " активирован!"
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


@router.callback_query(F.data == "shop_upgrade")
async def cb_shop_upgrade(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  upgrades_count = user[11]

  next_cost = (upgrades_count + 1) * 5
  next_boost = (upgrades_count + 1) * 0.002

  text = (
      f"⚡ <b>Прокачка скорости майнера</b>\n"
      f"🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
      f"Текущая скорость: <b>{user[5]:.4f} монет/сек</b>\n"
      f"Стоимость улучшения: <b>{next_cost} монет</b> ➡️ Прибавка: <b>+{next_boost:.3f} в сек</b>"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text=(
                      f"🚀 Улучшить скорость (+{next_boost:.3f} за"
                      f" {next_cost} монет)"
                  ),
                  callback_data="upgrade_miner_action",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 Назад в магазин", callback_data="shop_main"
              )
          ],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "upgrade_miner_action")
async def cb_upgrade_miner(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  upgrades_count = user[11]

  next_cost = (upgrades_count + 1) * 5
  next_boost = (upgrades_count + 1) * 0.002

  if user[2] < next_cost:
    await callback.answer(
        f"❌ Недостаточно монет на балансе (нужно {next_cost})!", show_alert=True
    )
    return

  cursor.execute(
      "UPDATE users SET balance = balance - ?, mining_speed = mining_speed +"
      " ?, miner_upgrades_count = miner_upgrades_count + 1 WHERE user_id = ?",
      (next_cost, next_boost, user_id),
  )
  conn.commit()
  await callback.answer(
      f"🎉 Скорость майнера увеличена на +{next_boost:.3f} в секунду!",
      show_alert=True,
  )
  await cb_shop_upgrade(callback)


@router.callback_query(F.data == "shop_exclusive")
async def cb_shop_exclusive(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  text = (
      f"💎 <b>Эксклюзивные майнеры</b>\n"
      f"🪙 Твой баланс: <b>{user[2]:.2f} монет</b>\n\n"
      "Выбери майнер для покупки:"
  )
  kb = []
  for m_key, m_val in EXCLUSIVE_MINERS.items():
    kb.append([
        InlineKeyboardButton(
            text=f"{m_val['name']} (+{m_val['speed']}/сек)",
            callback_data=f"buy_ex_{m_key}",
        )
    ])
  kb.append(
      [InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop_main")]
  )
  await callback.message.edit_text(
      text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
  )


@router.callback_query(F.data.startswith("buy_ex_"))
async def cb_buy_exclusive(callback: CallbackQuery):
  m_key = callback.data.replace("buy_ex_", "")
  m_val = EXCLUSIVE_MINERS[m_key]

  text = (
      f"💎 <b>Покупка: {m_val['name']}</b>\n"
      f"📈 Доходность: <b>+{m_val['speed']} монет/сек</b>\n\n"
      "Выбери удобный способ оплаты:"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text=f"⭐ Звездами ({m_val['stars']} Stars) [Авто]",
                  callback_data=f"pay_stars_{m_key}",
              )
          ],
          [
              InlineKeyboardButton(
                  text=f"💵 Рубли ({m_val['rub']} руб)",
                  callback_data=f"pay_rub_{m_key}",
              )
          ],
          [
              InlineKeyboardButton(
                  text=f"🪙 GRAM ({m_val['gram']} GRAM)",
                  callback_data=f"pay_gram_{m_key}",
              )
          ],
          [
              InlineKeyboardButton(
                  text=f"💲 USDT ({m_val['usdt']} USDT)",
                  callback_data=f"pay_usdt_{m_key}",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 К списку майнеров", callback_data="shop_exclusive"
              )
          ],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_with_stars(callback: CallbackQuery):
  m_key = callback.data.replace("pay_stars_", "")
  m_val = EXCLUSIVE_MINERS[m_key]

  prices = [LabeledPrice(label=m_val["name"], amount=m_val["stars"])]
  await bot.send_invoice(
      chat_id=callback.from_user.id,
      title=f"Покупка {m_val['name']}",
      description=(
          f"Приобретение эксклюзивного майнера со скоростью +{m_val['speed']}/сек"
      ),
      payload=f"miner_buy_{m_key}",
      currency="XTR",
      prices=prices,
  )
  await callback.answer()


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery):
  await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
  payload = message.successful_payment.invoice_payload
  if payload.startswith("miner_buy_"):
    m_key = payload.replace("miner_buy_", "")
    m_val = EXCLUSIVE_MINERS[m_key]
    user_id = message.from_user.id

    cursor.execute(
        "UPDATE users SET mining_speed = mining_speed + ? WHERE user_id = ?",
        (m_val["speed"], user_id),
    )
    conn.commit()
    await message.answer(
        f"🎉 Успешная оплата! Майнер <b>{m_val['name']}</b> успешно активирован!"
        f" Скорость увеличена на +{m_val['speed']}/сек.",
        parse_mode="HTML",
    )


@router.callback_query(
    F.data.startswith("pay_rub_")
    | F.data.startswith("pay_gram_")
    | F.data.startswith("pay_usdt_")
)
async def pay_manual(callback: CallbackQuery):
  parts = callback.data.split("_")
  pay_type = parts[1]
  m_key = f"{parts[2]}_{parts[3]}"
  m_val = EXCLUSIVE_MINERS[m_key]
  user_id = callback.from_user.id
  username = callback.from_user.username or callback.from_user.first_name

  if pay_type == "rub":
    method_name = "Рубли (Т-Банк)"
    details = f"Реквизиты Т-Банк: <code>{ADMIN_CARD}</code>\nСумма: <b>{m_val['rub']} руб.</b>"
  elif pay_type == "gram":
    method_name = "GRAM"
    details = f"Адрес Tonkeeper (GRAM): <code>{ADMIN_WALLET}</code>\nСумма: <b>{m_val['gram']} GRAM</b>"
  else:
    method_name = "USDT (TRC20)"
    details = f"Адрес USDT: <code>{ADMIN_WALLET}</code>\nСумма: <b>{m_val['usdt']} USDT</b>"

  cursor.execute(
      "INSERT INTO buy_requests (user_id, username, miner_name, method, status)"
      " VALUES (?, ?, ?, ?, 'pending')",
      (user_id, username, m_val["name"], method_name),
  )
  conn.commit()

  try:
    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>Новая заявка на покупку майнера!</b>\n"
        f"👤 Игрок: @{username} (ID: <code>{user_id}</code>)\n"
        f"💎 Майнер: <b>{m_val['name']}</b>\n"
        f"💳 Способ: <b>{method_name}</b>",
        parse_mode="HTML",
    )
  except Exception:
    pass

  text = (
      f"💳 <b>Оплата: {m_val['name']} ({method_name})</b>\n\n"
      f"{details}\n\n"
      "1. Переведи точную сумму по реквизитам выше.\n"
      "2. Заявка отправлена администратору. После проверки майнер будет зачислен!"
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# --- ЕЖЕДНЕВНЫЙ БОНУС ---
@router.callback_query(F.data == "daily")
async def cb_daily(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  last_bonus_str = user[7]

  now = datetime.now()
  if last_bonus_str:
    try:
      last_bonus = datetime.strptime(last_bonus_str, "%Y-%m-%d %H:%M:%S")
      if now - last_bonus < timedelta(days=1):
        await callback.answer(
            "⏳ Бонус уже получен! Приходи завтра.", show_alert=True
        )
        return
    except ValueError:
      pass

  bonus_amount = float(random.randint(1, 10))
  now_str = now.strftime("%Y-%m-%d %H:%M:%S")
  cursor.execute(
      "UPDATE users SET balance = balance + ?, last_daily_bonus = ? WHERE"
      " user_id = ?",
      (bonus_amount, now_str, user_id),
  )
  conn.commit()

  await callback.answer(
      f"🎁 Ты получил ежедневный бонус: +{bonus_amount:.0f} монет!",
      show_alert=True,
  )
  await cb_menu(callback, None)


# --- МИНИ-ИГРЫ ---
@router.callback_query(F.data == "menu_minigames")
async def open_minigames(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  games_menu_kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🪙 Орёл и Решка (Коэф x2)",
                  callback_data="game_start_coin",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🎯 Дартс (Коэф x1.8)", callback_data="game_start_darts"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🏀 Баскетбол (Коэф x1.8)",
                  callback_data="game_start_basket",
              )
          ],
          [
              InlineKeyboardButton(
                  text="⚽ Футбол (Коэф x1.8)",
                  callback_data="game_start_football",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🎰 Рулетка (777) (Коэф x3)",
                  callback_data="game_start_roulette",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🏠 Главное меню", callback_data="menu"
              )
          ],
      ]
  )
  await callback.message.edit_text(
      "🎮 <b>Мини-игры</b>\n\n"
      "• Лимит ставки: <b>от 1 до 100 монет</b>\n"
      "• Шанс выигрыша в стандартных играх: <b>35%</b>\n"
      "• Выбирай игру ниже:",
      reply_markup=games_menu_kb,
      parse_mode="HTML",
  )


@router.callback_query(F.data.startswith("game_start_"))
async def ask_game_bet(callback: CallbackQuery, state: FSMContext):
  game_type = callback.data.replace("game_start_", "")
  await state.update_data(game_type=game_type)
  await state.set_state(UserStates.waiting_for_game_bet)

  await callback.message.edit_text(
      "💰 <b>Сделай ставку</b>\n\n"
      "Отправь в ответном сообщении сумму ставки от <b>1</b> до <b>100 монет</b>:",
      reply_markup=back_kb(),
      parse_mode="HTML",
  )


@router.message(UserStates.waiting_for_game_bet)
async def process_game_bet(message: Message, state: FSMContext):
  user_id = message.from_user.id
  if not await check_sub_channel(user_id):
    await message.answer(
        "❌ Подпишитесь на канал @CoinFarmEmpire для продолжения!",
        reply_markup=get_sub_keyboard(),
    )
    return

  try:
    bet = float(message.text.strip())
  except ValueError:
    await message.answer(
        "❌ Введи число от 1 до 100 для ставки!", reply_markup=back_kb()
    )
    return

  if bet < 1 or bet > 100:
    await message.answer(
        "❌ Ставка должна быть в диапазоне от 1 до 100 монет!",
        reply_markup=back_kb(),
    )
    return

  user = get_user(user_id)
  if user[2] < bet:
    await message.answer(
        f"❌ Недостаточно средств! У тебя на балансе {user[2]:.2f} монет.",
        reply_markup=back_kb(),
    )
    return

  data = await state.get_data()
  game_type = data.get("game_type")

  cursor.execute(
      "UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id)
  )
  conn.commit()

  if game_type == "coin":
    await state.clear()
    if random.random() < 0.35:
      win_amt = bet * 2.0
      cursor.execute(
          "UPDATE users SET balance = balance + ? WHERE user_id = ?",
          (win_amt, user_id),
      )
      conn.commit()
      await message.answer(
          f"🎉 <b>Победа!</b> Выпал нужный исход!\n🪙 Вы выиграли: <b>+{win_amt:.1f}"
          " монет</b> (коэф x2)",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )
    else:
      await message.answer(
          f"😢 <b>Проигрыш!</b> Удача была не на вашей стороне.\n💸 Вы потеряли"
          f" ставку: {bet} монет",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )

  elif game_type in ["darts", "basket", "football"]:
    await state.clear()
    emoji_map = {"darts": "🎯", "basket": "🏀", "football": "⚽"}
    await message.answer(f"🎲 Бросаем снаряд...")
    await message.answer_dice(emoji=emoji_map[game_type])
    await asyncio.sleep(3)

    if random.random() < 0.35:
      win_amt = bet * 1.8
      cursor.execute(
          "UPDATE users SET balance = balance + ? WHERE user_id = ?",
          (win_amt, user_id),
      )
      conn.commit()
      await message.answer(
          f"🎉 <b>Победа!</b>\n🪙 Вы выиграли: <b>+{win_amt:.1f} монет</b> (коэф"
          " x1.8)",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )
    else:
      await message.answer(
          f"😢 <b>Проигрыш!</b> Не удалось победить.\n💸 Потеряно: {bet} монет",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )

  elif game_type == "roulette":
    await state.clear()
    await message.answer(f"🎰 Крутим рулетку...")
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)

    if random.random() < 0.08:
      win_amt = bet * 3.0
      cursor.execute(
          "UPDATE users SET balance = balance + ? WHERE user_id = ?",
          (win_amt, user_id),
      )
      conn.commit()
      await message.answer(
          f"💎 JACKPOT! <b>Выпало 777!</b>\n🪙 Ваш выигрыш: <b>+{win_amt:.1f}"
          " монет</b> (коэф x3)",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )
    else:
      await message.answer(
          f"😢 <b>Мимо!</b> Комбинация 777 не собралась.\n💸 Потеряно: {bet}"
          " монет",
          reply_markup=back_kb(),
          parse_mode="HTML",
      )


# --- ПРОМОКОДЫ ---
@router.callback_query(F.data == "promo")
async def cb_promo(callback: CallbackQuery, state: FSMContext):
  await state.set_state(UserStates.waiting_for_promo)
  text = (
      "🎟 <b>Активация промокода</b>\n\n"
      "Отправь в ответном сообщении текст промокода:"
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


@router.message(UserStates.waiting_for_promo)
async def process_promo(message: Message, state: FSMContext):
  user_id = message.from_user.id
  if not await check_sub_channel(user_id):
    await message.answer(
        "❌ Подпишитесь на канал @CoinFarmEmpire для продолжения!",
        reply_markup=get_sub_keyboard(),
    )
    return

  code = message.text.strip().upper()
  await state.clear()

  cursor.execute(
      "SELECT * FROM promo_activations WHERE user_id = ? AND code = ?",
      (user_id, code),
  )
  if cursor.fetchone():
    await message.answer(
        "❌ Ты уже активировал этот промокод ранее!", reply_markup=back_kb()
    )
    return

  cursor.execute(
      "SELECT reward, uses_left FROM promo_codes WHERE code = ?", (code,)
  )
  promo = cursor.fetchone()

  if not promo or promo[1] <= 0:
    await message.answer(
        "❌ Промокод недействителен или исчерпал лимит активаций.",
        reply_markup=back_kb(),
    )
    return

  reward, uses_left = promo

  cursor.execute(
      "UPDATE users SET balance = balance + ? WHERE user_id = ?",
      (reward, user_id),
  )
  cursor.execute(
      "UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?",
      (code,),
  )
  cursor.execute(
      "INSERT INTO promo_activations (user_id, code) VALUES (?, ?)",
      (user_id, code),
  )
  conn.commit()

  await message.answer(
      f"✅ Промокод успешно активирован! Начислено: +{reward} монет.",
      reply_markup=back_kb(),
  )


# --- РЕФЕРАЛЫ И ТОП ---
@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery):
  user_id = callback.from_user.id
  user = get_user(user_id)
  bot_info = await bot.get_me()
  ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

  cursor.execute("SELECT COUNT(*) FROM users WHERE invited_by = ?", (user_id,))
  invited_count = cursor.fetchone()[0]

  text = (
      "👥 <b>Реферальная система (10%)</b>\n\n"
      "Приглашай друзей и получай <b>10% пассивного дохода</b> от всего"
      " заработанного ими в сейфе!\n\n"
      f"🔗 Твоя реферальная ссылка:\n<code>{ref_link}</code>\n\n"
      f"📊 Приглашено: <b>{invited_count} друзей</b>\n"
      f"💰 Заработано с рефералов: <b>{user[9]:.2f} монет</b>"
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


@router.callback_query(F.data == "top")
async def cb_top(callback: CallbackQuery):
  cursor.execute(
      "SELECT username, mining_speed, balance FROM users ORDER BY balance DESC"
      " LIMIT 10"
  )
  top_players = cursor.fetchall()

  text = "🏆 <b>Топ-10 Майнеров:</b>\n\n"
  for i, (uname, speed, bal) in enumerate(top_players, start=1):
    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
    safe_name = uname if uname else "Майнер"
    text += (
        f"{medal} <b>{safe_name}</b> (Скорость: {speed:.4f}/сек) — {bal:.1f}"
        " 🪙\n"
    )

  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# --- ВЫВОД СРЕДСТВ ---
@router.callback_query(F.data == "withdraw")
async def cb_withdraw(callback: CallbackQuery, state: FSMContext):
  user_id = callback.from_user.id
  user = get_user(user_id)
  balance = user[2]
  MIN_WITHDRAW = 2500.0

  if balance < MIN_WITHDRAW:
    await callback.answer(
        f"❌ Мин. сумма для вывода: {MIN_WITHDRAW} монет. У тебя"
        f" {balance:.1f} монет",
        show_alert=True,
    )
    return

  await state.set_state(UserStates.waiting_for_withdraw_amount)
  text = (
      "💸 <b>Запрос на вывод средств</b>\n\n"
      f"Доступно на балансе: <b>{balance:.2f} монет</b>\n"
      f"Минимальная сумма: <b>{MIN_WITHDRAW} монет</b>\n\n"
      "Отправь в ответном сообщении сумму, которую хочешь вывести:"
  )
  await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


@router.message(UserStates.waiting_for_withdraw_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
  user_id = message.from_user.id
  if not await check_sub_channel(user_id):
    await message.answer(
        "❌ Подпишитесь на канал @CoinFarmEmpire для продолжения!",
        reply_markup=get_sub_keyboard(),
    )
    return

  try:
    amount = float(message.text.strip())
  except ValueError:
    await message.answer(
        "❌ Введи корректное число для суммы вывода!", reply_markup=back_kb()
    )
    return

  user = get_user(user_id)
  if amount < 2500.0 or amount > user[2]:
    await message.answer(
        "❌ Неверная сумма! Она должна быть от 2500 и не превышать твой баланс.",
        reply_markup=back_kb(),
    )
    return

  await state.update_data(withdraw_amount=amount)
  await state.set_state(UserStates.waiting_for_withdraw_method)

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(text="💲 USDT", callback_data="w_method_USDT"),
              InlineKeyboardButton(text="🪙 GRAM", callback_data="w_method_GRAM"),
              InlineKeyboardButton(
                  text="⭐ STARS", callback_data="w_method_STARS"
              ),
          ],
          [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
      ]
  )
  await message.answer(
      "💳 Выбери способ вывода средств:", reply_markup=kb, parse_mode="HTML"
  )


@router.callback_query(F.data.startswith("w_method_"))
async def cb_withdraw_method(callback: CallbackQuery, state: FSMContext):
  method = callback.data.replace("w_method_", "")
  await state.update_data(withdraw_method=method)
  await state.set_state(UserStates.waiting_for_withdraw_wallet)

  await callback.message.edit_text(
      f"📥 Выбран способ: <b>{method}</b>\n\n"
      "Теперь отправь в ответном сообщении адрес своего криптокошелька или реквизиты для получения вывода:",
      reply_markup=back_kb(),
      parse_mode="HTML",
  )


@router.message(UserStates.waiting_for_withdraw_wallet)
async def process_withdraw_wallet(message: Message, state: FSMContext):
  user_id = message.from_user.id
  if not await check_sub_channel(user_id):
    await message.answer(
        "❌ Подпишитесь на канал @CoinFarmEmpire для продолжения!",
        reply_markup=get_sub_keyboard(),
    )
    return

  username = message.from_user.username or message.from_user.first_name
  wallet = message.text.strip()
  data = await state.get_data()
  amount = data.get("withdraw_amount")
  method = data.get("withdraw_method")

  await state.clear()

  user = get_user(user_id)
  if user[2] < amount:
    await message.answer(
        "❌ Ошибка: недостаточно средств на балансе.", reply_markup=back_kb()
    )
    return

  cursor.execute(
      "UPDATE users SET balance = balance - ? WHERE user_id = ?",
      (amount, user_id),
  )
  cursor.execute(
      "INSERT INTO withdraw_requests (user_id, username, amount, method,"
      " wallet, status) VALUES (?, ?, ?, ?, ?, 'pending')",
      (user_id, username, amount, method, wallet),
  )
  conn.commit()

  try:
    await bot.send_message(
        ADMIN_ID,
        f"💸 <b>Новая заявка на вывод!</b>\n"
        f"👤 Игрок: @{username} (ID: <code>{user_id}</code>)\n"
        f"💰 Сумма: <b>{amount} монет</b>\n"
        f"💳 Метод: <b>{method}</b>\n"
        f"📬 Кошелек: <code>{wallet}</code>",
        parse_mode="HTML",
    )
  except Exception:
    pass

  await message.answer(
      "✅ <b>Заявка на вывод успешно принята!</b>\nАдминистратор проверит её и переведет средства в ближайшее время.",
      reply_markup=back_kb(),
      parse_mode="HTML",
  )


# --- АДМИН-ПАНЕЛЬ ---
@router.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    await callback.answer("❌ Доступ запрещен", show_alert=True)
    return

  cursor.execute("SELECT COUNT(*) FROM users")
  total_users = cursor.fetchone()[0]
  cursor.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'")
  pending_w = cursor.fetchone()[0]
  cursor.execute("SELECT COUNT(*) FROM buy_requests WHERE status='pending'")
  pending_b = cursor.fetchone()[0]

  text = (
      "🛠 <b>Админ-панель</b>\n\n"
      f"👥 Игроков в базе: <b>{total_users}</b>\n"
      f"💸 Заявок на вывод ждет: <b>{pending_w}</b>\n"
      f"🛒 Заявок на покупку (майнеры/автосбор): <b>{pending_b}</b>"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📋 Заявки на вывод", callback_data="admin_withdraws"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🛒 Заявки на покупку", callback_data="admin_buys"
              )
          ],
          [
              InlineKeyboardButton(
                  text="⚙️ Выдать / Забрать монеты",
                  callback_data="admin_balance_manage",
              )
          ],
          [
              InlineKeyboardButton(
                  text="🎟 Управление промокодами",
                  callback_data="admin_promo_manage",
              )
          ],
          [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
      ]
  )
  await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_withdraws")
async def cb_admin_withdraws(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  cursor.execute(
      "SELECT id, user_id, username, amount, method, wallet FROM"
      " withdraw_requests WHERE status='pending' LIMIT 5"
  )
  requests = cursor.fetchall()

  if not requests:
    await callback.answer("✅ Нет активных заявок на вывод!", show_alert=True)
    return

  for req_id, u_id, uname, amount, method, wallet in requests:
    text = (
        f"💸 <b>Заявка на вывод #{req_id}</b>\n"
        f"👤 Игрок: @{uname} (ID: <code>{u_id}</code>)\n"
        f"💰 Сумма: <b>{amount} монет</b>\n"
        f"💳 Метод: <b>{method}</b>\n"
        f"📬 Кошелек: <code>{wallet}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выплачено", callback_data=f"pay_ok_{req_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить (возврат)",
                    callback_data=f"pay_no_{req_id}",
                ),
            ]
        ]
    )
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
  await callback.answer()


@router.callback_query(F.data.startswith("pay_ok_"))
async def cb_pay_ok(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  req_id = int(callback.data.split("_")[2])
  cursor.execute(
      "UPDATE withdraw_requests SET status = 'paid' WHERE id = ?", (req_id,)
  )
  conn.commit()
  await callback.message.edit_text(f"✅ Заявка на вывод #{req_id} закрыта (выплачено).")


@router.callback_query(F.data.startswith("pay_no_"))
async def cb_pay_no(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  req_id = int(callback.data.split("_")[2])
  cursor.execute(
      "SELECT user_id, amount FROM withdraw_requests WHERE id = ?", (req_id,)
  )
  res = cursor.fetchone()
  if res:
    u_id, amount = res
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, u_id),
    )
    cursor.execute(
        "UPDATE withdraw_requests SET status = 'rejected' WHERE id = ?",
        (req_id,),
    )
    conn.commit()
    try:
      await bot.send_message(
          u_id,
          f"❌ Ваша заявка на вывод #{req_id} была отклонена администратором. Средства ({amount} монет) возвращены на баланс.",
          parse_mode="HTML",
      )
    except Exception:
      pass

  await callback.message.edit_text(
      f"❌ Заявка на вывод #{req_id} отклонена, средства возвращены пользователю."
  )


@router.callback_query(F.data == "admin_buys")
async def cb_admin_buys(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  cursor.execute(
      "SELECT id, user_id, username, miner_name, method FROM buy_requests"
      " WHERE status='pending' LIMIT 5"
  )
  requests = cursor.fetchall()

  if not requests:
    await callback.answer("✅ Нет заявок на покупку!", show_alert=True)
    return

  for req_id, u_id, uname, m_name, method in requests:
    text = (
        f"🛒 <b>Заявка на покупку #{req_id}</b>\n"
        f"👤 Игрок: @{uname} (ID: <code>{u_id}</code>)\n"
        f"💎 Товар: <b>{m_name}</b>\n"
        f"💳 Оплата через: <b>{method}</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить (Выдать)",
                    callback_data=f"buy_ok_{req_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"buy_no_{req_id}"
                ),
            ]
        ]
    )
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
  await callback.answer()


@router.callback_query(F.data.startswith("buy_ok_"))
async def cb_buy_ok(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  req_id = int(callback.data.split("_")[2])
  cursor.execute(
      "SELECT user_id, miner_name FROM buy_requests WHERE id = ?", (req_id,)
  )
  res = cursor.fetchone()
  if res:
    u_id, m_name = res

    if "Автосбор" in m_name:
      cursor.execute(
          "UPDATE users SET has_autocollect = 1 WHERE user_id = ?", (u_id,)
      )
      cursor.execute(
          "UPDATE buy_requests SET status = 'approved' WHERE id = ?", (req_id,)
      )
      conn.commit()
      try:
        await bot.send_message(
            u_id,
            "🎉 Администратор подтвердил оплату! 🤖 <b>Автосбор сейфа</b> успешно"
            " активирован!",
            parse_mode="HTML",
        )
      except Exception:
        pass
    else:
      speed_to_add = 0.05
      for m_k, m_v in EXCLUSIVE_MINERS.items():
        if m_v["name"] == m_name:
          speed_to_add = m_v["speed"]
          break

      cursor.execute(
          "UPDATE users SET mining_speed = mining_speed + ? WHERE user_id = ?",
          (speed_to_add, u_id),
      )
      cursor.execute(
          "UPDATE buy_requests SET status = 'approved' WHERE id = ?", (req_id,)
      )
      conn.commit()

      try:
        await bot.send_message(
            u_id,
            f"🎉 Администратор подтвердил вашу оплату! Майнер <b>{m_name}</b>"
            " успешно активирован!",
            parse_mode="HTML",
        )
      except Exception:
        pass

  await callback.message.edit_text(f"✅ Заявка на покупку #{req_id} одобрена.")


@router.callback_query(F.data.startswith("buy_no_"))
async def cb_buy_no(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  req_id = int(callback.data.split("_")[2])
  cursor.execute(
      "UPDATE buy_requests SET status = 'rejected' WHERE id = ?", (req_id,)
  )
  conn.commit()
  await callback.message.edit_text(f"❌ Заявка на покупку #{req_id} отклонена.")


@router.callback_query(F.data == "admin_balance_manage")
async def cb_admin_balance_manage(callback: CallbackQuery, state: FSMContext):
  if callback.from_user.id != ADMIN_ID:
    return
  await state.set_state(AdminStates.waiting_for_balance_change)
  await callback.message.edit_text(
      "⚙️ <b>Изменение баланса игрока</b>\n\n"
      "Отправь в чат данные в формате: <code>ID СУММА</code>\n"
      "• Чтобы <b>выдать</b>: <code>123456789 +500</code>\n"
      "• Чтобы <b>забрать</b>: <code>123456789 -200</code>",
      reply_markup=back_kb(),
      parse_mode="HTML",
  )


@router.message(AdminStates.waiting_for_balance_change)
async def process_admin_balance(message: Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  await state.clear()

  try:
    parts = message.text.split()
    target_id = int(parts[0])
    diff = float(parts[1])

    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?", (target_id,)
    )
    res = cursor.fetchone()
    if not res:
      await message.answer("❌ Игрок не найден в базе.")
      return

    new_bal = max(0.0, res[0] + diff)
    cursor.execute(
        "UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_id)
    )
    conn.commit()

    await message.answer(
        f"✅ Баланс игрока <code>{target_id}</code> успешно изменен. Новый баланс:"
        f" {new_bal:.2f}",
        parse_mode="HTML",
    )
  except Exception:
    await message.answer(
        "❌ Ошибка формата! Используй: <code>ID +СУММА</code> или <code>ID"
        " -СУММА</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_promo_manage")
async def cb_admin_promo_manage(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return

  cursor.execute("SELECT code, reward, uses_left FROM promo_codes")
  promos = cursor.fetchall()

  text = "🎟 <b>Активные промокоды:</b>\n\n"
  kb = []

  if promos:
    for code, reward, uses in promos:
      text += (
          f"• Код: <b>{code}</b> | Награда: <b>{reward}</b> | Осталось активаций:"
          f" <b>{uses}</b>\n"
      )
      kb.append([
          InlineKeyboardButton(
              text=f"🗑 Удалить {code}", callback_data=f"del_promo_{code}"
          )
      ])
  else:
    text += "<i>Нет активных промокодов.</i>\n"

  kb.append([
      InlineKeyboardButton(
          text="➕ Создать новый промокод", callback_data="admin_create_promo"
      )
  ])
  kb.append([InlineKeyboardButton(text="🔙 В админку", callback_data="admin")])

  await callback.message.edit_text(
      text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
  )


@router.callback_query(F.data.startswith("del_promo_"))
async def cb_del_promo(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  code = callback.data.replace("del_promo_", "")
  cursor.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
  conn.commit()
  await callback.answer(f"🗑 Промокод {code} удален!", show_alert=True)
  await cb_admin_promo_manage(callback)


@router.callback_query(F.data == "admin_create_promo")
async def cb_admin_create_promo(callback: CallbackQuery, state: FSMContext):
  if callback.from_user.id != ADMIN_ID:
    return
  await state.set_state(AdminStates.waiting_for_promo_create)
  await callback.message.edit_text(
      "➕ <b>Создание промокода</b>\n\n"
      "Отправь данные в формате: <code>КОД НАГРАДА ЛИМИТ_АКТИВАЦИЙ</code>\n"
      "Пример: <code>BONUS2026 500 25</code>",
      reply_markup=back_kb(),
      parse_mode="HTML",
  )


@router.message(AdminStates.waiting_for_promo_create)
async def process_admin_create_promo(message: Message, state: FSMContext):
  if message.from_user.id != ADMIN_ID:
    return
  await state.clear()

  try:
    parts = message.text.split()
    code = parts[0].strip().upper()
    reward = float(parts[1])
    uses = int(parts[2])

    cursor.execute(
        "INSERT OR REPLACE INTO promo_codes (code, reward, uses_left) VALUES"
        " (?, ?, ?)",
        (code, reward, uses),
    )
    conn.commit()

    await message.answer(
        f"✅ Промокод <b>{code}</b> на <b>{reward}</b> монет (лимит: {uses})"
        " успешно создан!",
        parse_mode="HTML",
    )
  except Exception:
    await message.answer(
        "❌ Ошибка! Используй формат: <code>КОД НАГРАДА ЛИМИТ</code>",
        parse_mode="HTML",
    )


# --- ФОНОВЫЙ ПРОЦЕСС АВТО-МАЙНИНГА ---
async def background_mining_loop():
  while True:
    await asyncio.sleep(5)
    try:
      cursor.execute("SELECT user_id FROM users")
      users = cursor.fetchall()
      for (u_id,) in users:
        calculate_mining(u_id)
    except Exception:
      pass


# --- ЗАПУСК ---
async def main():
  dp.include_router(router)
  await bot.delete_webhook(drop_pending_updates=True)
  asyncio.create_task(background_mining_loop())
  print("Бот успешно запущен, проверка подписки активирована...")
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
