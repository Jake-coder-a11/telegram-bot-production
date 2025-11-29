import psycopg2
from config import DATABASE_URL

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
            # Пользователи
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
            
            # Заявки
            cur.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    admin_id BIGINT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Отклики на заявки
            cur.execute('''
                CREATE TABLE IF NOT EXISTS order_responses (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER REFERENCES orders(id),
                    user_id BIGINT REFERENCES users(telegram_id),
                    status TEXT DEFAULT 'responded',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Администраторы
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