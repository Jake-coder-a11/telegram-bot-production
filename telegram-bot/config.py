import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Без ошибок если ADMIN_IDS пустой
admin_ids = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(x.strip()) for x in admin_ids.split(',') if x.strip()] if admin_ids else []