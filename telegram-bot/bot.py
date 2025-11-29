import asyncio
import logging
import re
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import psycopg2
from config import BOT_TOKEN, DATABASE_URL, ADMIN_IDS

logging.basicConfig(level=logging.INFO)

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self):
        self.conn = None
    
    def connect(self):
        try:
            self.conn = psycopg2.connect(DATABASE_URL)
            self.create_tables()
            print("✅ База данных подключена и таблицы созданы!")
        except Exception as e:
            print(f"❌ Ошибка подключения к базе: {e}")
    
    def create_tables(self):
        with self.conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    birth_date TEXT,
                    inn TEXT,
                    account_number TEXT,
                    passport TEXT,
                    work_type TEXT[],
                    agreed_to_terms BOOLEAN DEFAULT FALSE,
                    agreed_to_rules BOOLEAN DEFAULT FALSE,
                    registration_stage INTEGER DEFAULT 1,
                    is_active BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            cur.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    admin_id BIGINT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            cur.execute('''
                CREATE TABLE IF NOT EXISTS order_responses (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER REFERENCES orders(id),
                    user_id BIGINT REFERENCES users(telegram_id),
                    status TEXT DEFAULT 'responded',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            cur.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE,
                    username TEXT,
                    full_name TEXT,
                    role TEXT DEFAULT 'admin',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            self.conn.commit()

# ===== СОСТОЯНИЯ =====
class Registration(StatesGroup):
    fio = State()
    phone = State()
    terms = State()
    rules = State()
    work_type = State()
    birth_date = State()
    inn = State()
    account_number = State()
    passport = State()

class OrderStates(StatesGroup):
    waiting_for_description = State()

# ===== ОСНОВНОЙ КОД =====
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    db = Database()
    
    db.connect()

    # ===== КЛАВИАТУРЫ =====
    def get_agreement_keyboard(show_back=True):
        buttons = []
        if show_back:
            buttons.append(InlineKeyboardButton(text="Назад", callback_data="back"))
        buttons.extend([
            InlineKeyboardButton(text="Согласен", callback_data="agree"),
            InlineKeyboardButton(text="Не согласен", callback_data="disagree")
        ])
        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    def get_work_type_keyboard(selected_works=None):
        if selected_works is None:
            selected_works = []
        
        works = ["Хелпер", "Грузчик", "Монтажник"]
        keyboard = []
        
        for work in works:
            status = "✅" if work in selected_works else "❌"
            keyboard.append([InlineKeyboardButton(
                text=f"{status} {work}", 
                callback_data=f"toggle_{work}"
            )])
        
        keyboard.append([InlineKeyboardButton(text="Подтвердить выбор", callback_data="confirm_works")])
        keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back"), 
                        InlineKeyboardButton(text="Отмена", callback_data="cancel")])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def get_navigation_keyboard(show_back=True, show_cancel=True):
        buttons = []
        if show_back:
            buttons.append(InlineKeyboardButton(text="Назад", callback_data="back"))
        if show_cancel:
            buttons.append(InlineKeyboardButton(text="Отмена", callback_data="cancel"))
        return InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

    def get_main_menu_keyboard():
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Мой профиль", callback_data="profile")],
                [InlineKeyboardButton(text="Завершить регистрацию", callback_data="complete_reg")],
                [InlineKeyboardButton(text="Активные заявки", callback_data="active_orders")]
            ]
        )

    def get_complete_registration_keyboard():
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Дата рождения", callback_data="set_birth_date")],
                [InlineKeyboardButton(text="ИНН", callback_data="set_inn")],
                [InlineKeyboardButton(text="Расчетный счет", callback_data="set_account")],
                [InlineKeyboardButton(text="Паспорт", callback_data="set_passport")],
                [InlineKeyboardButton(text="Главное меню", callback_data="main_menu")]
            ]
        )

    # ===== ВАЛИДАТОРЫ =====
    def validate_fio(fio):
        fio_clean = fio.strip()
        parts = fio_clean.split()
        if len(parts) != 3:
            return False
        return all(len(part) >= 2 and part.isalpha() for part in parts)

    def validate_phone(phone):
        phone_clean = re.sub(r'[^\d+]', '', phone.strip())
        if phone_clean.startswith('8'):
            phone_clean = '+7' + phone_clean[1:]
        return bool(re.match(r'^\+7\d{10}$', phone_clean))

    def format_phone(phone):
        phone_clean = re.sub(r'[^\d+]', '', phone.strip())
        if phone_clean.startswith('8'):
            phone_clean = '+7' + phone_clean[1:]
        return phone_clean

    def validate_date(date_str):
        try:
            date_clean = date_str.strip()
            datetime.strptime(date_clean, '%d.%m.%Y')
            return True
        except ValueError:
            return False

    def validate_inn(inn):
        inn_clean = inn.strip()
        return inn_clean.isdigit() and len(inn_clean) == 12

    def validate_account(account):
        account_clean = account.strip()
        return account_clean.isdigit() and len(account_clean) == 20

    def validate_passport(passport):
        passport_clean = passport.strip()
        return passport_clean.isdigit() and len(passport_clean) == 10

    # ===== ПРОВЕРКА АДМИНА =====
    def is_admin(user_id):
        return user_id in ADMIN_IDS

    # ===== ОБРАБОТЧИКИ НАВИГАЦИИ =====
    @dp.callback_query(F.data == "back")
    async def back_handler(callback: CallbackQuery, state: FSMContext):
        current_state = await state.get_state()
        user_data = await state.get_data()
        
        if current_state == Registration.phone.state:
            await callback.message.edit_text("Введите ваше ФИО (3 слова через пробел):")
            await state.set_state(Registration.fio)
            
        elif current_state == Registration.terms.state:
            await callback.message.edit_text("Введите номер телефона:\n\nФормат: +79991234567 или 89991234567")
            await state.set_state(Registration.phone)
            
        elif current_state == Registration.rules.state:
            terms_text = 'Я согласен с <a href="https://example.com/terms">условиями обработки данных</a>'
            await callback.message.edit_text(terms_text, parse_mode='HTML', reply_markup=get_agreement_keyboard())
            await state.set_state(Registration.terms)
            
        elif current_state == Registration.work_type.state:
            rules_text = 'Я согласен с <a href="https://example.com/rules">правилами использования сервиса</a>'
            await callback.message.edit_text(rules_text, parse_mode='HTML', reply_markup=get_agreement_keyboard(show_back=True))
            await state.set_state(Registration.rules)
            
        elif current_state == Registration.birth_date.state:
            await callback.message.edit_text("Выберите виды работ:")
            await state.set_state(Registration.work_type)
            
        elif current_state == Registration.inn.state:
            await callback.message.edit_text("Введите дату рождения (формат: ДД.ММ.ГГГГ):")
            await state.set_state(Registration.birth_date)
            
        elif current_state == Registration.account_number.state:
            await callback.message.edit_text("Введите ИНН (12 цифр):")
            await state.set_state(Registration.inn)
            
        elif current_state == Registration.passport.state:
            await callback.message.edit_text("Введите расчетный счет (20 цифр):")
            await state.set_state(Registration.account_number)
            
        await callback.answer()

    @dp.callback_query(F.data == "cancel")
    async def cancel_handler(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("Регистрация отменена. Используйте /start для начала.")
        await callback.answer()

    @dp.callback_query(F.data == "main_menu")
    async def main_menu_handler(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu_keyboard())
        await callback.answer()

    # ===== ОСНОВНАЯ РЕГИСТРАЦИЯ =====
    @dp.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext):
        with db.conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (message.from_user.id,))
            user = cur.fetchone()
        
        if user:
            await message.answer("Вы уже зарегистрированы!", reply_markup=get_main_menu_keyboard())
            return
        
        await message.answer(
            "Добро пожаловать! Начнем регистрацию.\n\nВведите ваше ФИО (3 слова через пробел):",
            reply_markup=get_navigation_keyboard(show_back=False, show_cancel=True)
        )
        await state.set_state(Registration.fio)

    @dp.message(Registration.fio)
    async def process_fio(message: Message, state: FSMContext):
        if validate_fio(message.text):
            await state.update_data(fio=message.text.strip())
            await message.answer(
                "Отлично! Теперь введите номер телефона:\n\nФормат: +79991234567 или 89991234567",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )
            await state.set_state(Registration.phone)
        else:
            await message.answer(
                "Ошибка: введите ровно 3 слова (только буквы и пробелы)",
                reply_markup=get_navigation_keyboard(show_back=False, show_cancel=True)
            )

    @dp.message(Registration.phone)
    async def process_phone(message: Message, state: FSMContext):
        if validate_phone(message.text):
            formatted_phone = format_phone(message.text)
            await state.update_data(phone=formatted_phone)
            
            terms_text = 'Я согласен с <a href="https://example.com/terms">условиями обработки данных</a>'
            await message.answer(
                terms_text, 
                parse_mode='HTML', 
                reply_markup=get_agreement_keyboard(show_back=True)
            )
            await state.set_state(Registration.terms)
        else:
            await message.answer(
                "Ошибка: неверный формат номера. Используйте: +79991234567 или 89991234567",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )

    @dp.callback_query(Registration.terms, F.data.in_(["agree", "disagree"]))
    async def process_terms(callback: CallbackQuery, state: FSMContext):
        if callback.data == "agree":
            await callback.message.edit_text("Вы согласились на обработку данных")
            
            rules_text = 'Я согласен с <a href="https://example.com/rules">правилами использования сервиса</a>'
            await callback.message.answer(
                rules_text, 
                parse_mode='HTML', 
                reply_markup=get_agreement_keyboard(show_back=True)
            )
            await state.set_state(Registration.rules)
        else:
            terms_text = 'Для продолжения необходимо согласие. Я согласен с <a href="https://example.com/terms">условиями обработки данных</a>'
            await callback.message.edit_text(
                terms_text, 
                parse_mode='HTML', 
                reply_markup=get_agreement_keyboard(show_back=True)
            )
        await callback.answer()

    @dp.callback_query(Registration.rules, F.data.in_(["agree", "disagree"]))
    async def process_rules(callback: CallbackQuery, state: FSMContext):
        if callback.data == "agree":
            await callback.message.edit_text("Вы приняли правила использования")
            
            user_data = await state.get_data()
            selected_works = user_data.get('selected_works', [])
            await callback.message.answer(
                "Выберите виды работ:", 
                reply_markup=get_work_type_keyboard(selected_works)
            )
            await state.set_state(Registration.work_type)
        else:
            rules_text = 'Для продолжения необходимо принять правила. Я согласен с <a href="https://example.com/rules">правилами использования сервиса</a>'
            await callback.message.edit_text(
                rules_text, 
                parse_mode='HTML', 
                reply_markup=get_agreement_keyboard(show_back=True)
            )
        await callback.answer()

    @dp.callback_query(Registration.work_type, F.data.startswith("toggle_"))
    async def toggle_work_type(callback: CallbackQuery, state: FSMContext):
        work_type = callback.data.replace("toggle_", "")
        user_data = await state.get_data()
        selected_works = user_data.get('selected_works', [])
        
        if work_type in selected_works:
            selected_works.remove(work_type)
        else:
            selected_works.append(work_type)
        
        await state.update_data(selected_works=selected_works)
        await callback.message.edit_reply_markup(reply_markup=get_work_type_keyboard(selected_works))
        await callback.answer()

    @dp.callback_query(Registration.work_type, F.data == "confirm_works")
    async def confirm_works(callback: CallbackQuery, state: FSMContext):
        user_data = await state.get_data()
        selected_works = user_data.get('selected_works', [])
        
        if not selected_works:
            await callback.answer("Выберите хотя бы один вид работ")
            return
        
        with db.conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO users (telegram_id, username, full_name, phone, work_type, agreed_to_terms, agreed_to_rules, registration_stage) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (callback.from_user.id, callback.from_user.username, user_data['fio'], user_data['phone'], selected_works, True, True, 5)
            )
            db.conn.commit()
        
        work_types_text = ", ".join(selected_works)
        await callback.message.edit_text(f"Вы выбрали: {work_types_text}")
        await callback.message.answer(
            "Основная регистрация завершена!", 
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        await callback.answer()

    # ===== ПОЛНАЯ РЕГИСТРАЦИЯ =====
    @dp.callback_query(F.data == "complete_reg")
    async def complete_reg_handler(callback: CallbackQuery):
        with db.conn.cursor() as cur:
            cur.execute("SELECT registration_stage FROM users WHERE telegram_id = %s", (callback.from_user.id,))
            result = cur.fetchone()
            
        if not result or result[0] < 5:
            await callback.message.answer("Сначала завершите основную регистрацию")
            return
            
        await callback.message.edit_text(
            "Завершение регистрации. Выберите данные для заполнения:",
            reply_markup=get_complete_registration_keyboard()
        )
        await callback.answer()

    @dp.callback_query(F.data == "set_birth_date")
    async def set_birth_date_handler(callback: CallbackQuery, state: FSMContext):
        await callback.message.edit_text(
            "Введите дату рождения (формат: ДД.ММ.ГГГГ):",
            reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
        )
        await state.set_state(Registration.birth_date)
        await callback.answer()

    @dp.message(Registration.birth_date)
    async def process_birth_date(message: Message, state: FSMContext):
        if validate_date(message.text):
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET birth_date = %s, registration_stage = GREATEST(registration_stage, 6) WHERE telegram_id = %s",
                    (message.text.strip(), message.from_user.id)
                )
                db.conn.commit()
            
            await message.answer(
                "✅ Дата рождения сохранена!",
                reply_markup=get_complete_registration_keyboard()
            )
            await state.clear()
        else:
            await message.answer(
                "❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )

    @dp.callback_query(F.data == "set_inn")
    async def set_inn_handler(callback: CallbackQuery, state: FSMContext):
        await callback.message.edit_text(
            "Введите ИНН (12 цифр):",
            reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
        )
        await state.set_state(Registration.inn)
        await callback.answer()

    @dp.message(Registration.inn)
    async def process_inn(message: Message, state: FSMContext):
        if validate_inn(message.text):
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET inn = %s, registration_stage = GREATEST(registration_stage, 7) WHERE telegram_id = %s",
                    (message.text.strip(), message.from_user.id)
                )
                db.conn.commit()
            
            await message.answer(
                "✅ ИНН сохранен!",
                reply_markup=get_complete_registration_keyboard()
            )
            await state.clear()
        else:
            await message.answer(
                "❌ Неверный ИНН. Должно быть 12 цифр.",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )

    @dp.callback_query(F.data == "set_account")
    async def set_account_handler(callback: CallbackQuery, state: FSMContext):
        await callback.message.edit_text(
            "Введите расчетный счет (20 цифр):",
            reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
        )
        await state.set_state(Registration.account_number)
        await callback.answer()

    @dp.message(Registration.account_number)
    async def process_account(message: Message, state: FSMContext):
        if validate_account(message.text):
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET account_number = %s, registration_stage = GREATEST(registration_stage, 8) WHERE telegram_id = %s",
                    (message.text.strip(), message.from_user.id)
                )
                db.conn.commit()
            
            await message.answer(
                "✅ Расчетный счет сохранен!",
                reply_markup=get_complete_registration_keyboard()
            )
            await state.clear()
        else:
            await message.answer(
                "❌ Неверный номер счета. Должно быть 20 цифр.",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )

    @dp.callback_query(F.data == "set_passport")
    async def set_passport_handler(callback: CallbackQuery, state: FSMContext):
        await callback.message.edit_text(
            "Введите паспортные данные (10 цифр):",
            reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
        )
        await state.set_state(Registration.passport)
        await callback.answer()

    @dp.message(Registration.passport)
    async def process_passport(message: Message, state: FSMContext):
        passport = message.text.strip()
        
        if validate_passport(passport):
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET passport = %s, registration_stage = 9, is_active = TRUE WHERE telegram_id = %s",
                    (passport, message.from_user.id)
                )
                db.conn.commit()
            
            await message.answer(
                "🎉 Полная регистрация завершена! Ваш аккаунт активирован.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
        else:
            await message.answer(
                f"❌ Неверные паспортные данные. Должно быть 10 цифр. Вы ввели: {len(passport)}",
                reply_markup=get_navigation_keyboard(show_back=True, show_cancel=True)
            )

    # ===== ЛИЧНЫЙ КАБИНЕТ =====
    @dp.callback_query(F.data == "profile")
    async def profile_handler(callback: CallbackQuery):
        with db.conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (callback.from_user.id,))
            user = cur.fetchone()
        
        if not user:
            await callback.message.answer("Вы не зарегистрированы. Используйте /start")
            return
        
        profile_text = "👤 Ваш профиль:\n\n"
        profile_text += f"• ФИО: {user[3] or 'Не указано'}\n"
        profile_text += f"• Телефон: {user[4] or 'Не указан'}\n"
        profile_text += f"• Вид работы: {', '.join(user[9]) if user[9] else 'Не указан'}\n"
        
        if user[5]: profile_text += f"• Дата рождения: {user[5]}\n"
        if user[6]: profile_text += f"• ИНН: {user[6]}\n"
        if user[7]: profile_text += f"• Расчетный счет: {user[7]}\n"
        if user[8]: profile_text += f"• Паспорт: {user[8]}\n"
        
        profile_text += f"• Статус: {'✅ Активен' if user[13] else '⏳ В процессе'}"
        profile_text += f"\n• Этап регистрации: {user[12]}/9"
        
        await callback.message.answer(profile_text, reply_markup=get_main_menu_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "active_orders")
    async def active_orders_handler(callback: CallbackQuery):
        with db.conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE status = 'active' ORDER BY created_at DESC LIMIT 5")
            orders = cur.fetchall()
        
        if not orders:
            await callback.message.answer("📭 Активных заявок пока нет", reply_markup=get_main_menu_keyboard())
            return
        
        orders_text = "📋 Активные заявки:\n\n"
        for order in orders:
            orders_text += f"🔹 {order[1]}\n"
            orders_text += f"   ID: {order[0]} | 📅 {order[4].strftime('%d.%m.%Y')}\n\n"
        
        await callback.message.answer(orders_text, reply_markup=get_main_menu_keyboard())
        await callback.answer()

    # ===== АДМИН-ПАНЕЛЬ (упрощенная) =====
    @dp.message(Command("admin"))
    async def admin_panel(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        admin_text = (
            "👨‍💼 Панель администратора:\n\n"
            "/add_order - Добавить заявку\n"
            "/stats - Статистика\n"
            "/users - Список пользователей"
        )
        await message.answer(admin_text)

    # ... остальные админ-команды без изменений

    print("✅ Бот запущен со ВСЕМИ этапами регистрации!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())