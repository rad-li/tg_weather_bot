import asyncio
import logging
import os
from datetime import datetime
import requests
import requests_cache                               # Расширение для requests — добавляет автоматическое кэширование HTTP-ответов
from dotenv import load_dotenv                      # Загружает переменные окружения из файла .env (токены, API-ключи)
from aiogram import Bot, Dispatcher, F              # Основные классы aiogram: Bot (подключение к Telegram), Dispatcher (обработка сообщений), F (фильтры)
from aiogram.filters import Command, CommandStart   # Фильтры для команд: Command (любая /команда), CommandStart (/start)
from aiogram.types import Message                   # Тип данных для представления входящих сообщений Telegram
from aiogram.client.default import DefaultBotProperties  # Настройки по умолчанию для Bot
from requests_cache import CachedResponse           # Класс для работы с кэшированными ответами requests_cache


# Загружаем переменные окружения
load_dotenv()

# Токены и настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
CACHE_EXPIRE = int(os.getenv('CACHE_EXPIRE', '600'))


# Проверяем указаны ли токены бота и openweather
if not BOT_TOKEN or not WEATHER_API_KEY:
    print("Создайте .env с BOT_TOKEN и WEATHER_API_KEY!")
    exit(1)


# Кэширование HTTP-запросов
requests_cache.install_cache(
    'weather_cache',
    expire_after=CACHE_EXPIRE,
    stale_if_error=True
)


# Логирование в терминал для отладки
logging.basicConfig(level=logging.INFO)

# Логирование в файл
logging.basicConfig(
    level=logging.INFO,
    filename='bot.log',      # Логи пишутся в файл bot.log
    filemode='a',            # 'a' - добавление, 'w' - перезапись
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def check_bot_token():
    """Проверяет валидность токена бота"""
    try:
        bot = Bot(token=BOT_TOKEN)
        me = await bot.get_me()
        await bot.session.close()
        cache_minutes = CACHE_EXPIRE / 60
        logger.info(f"Бот готов! Кэш: {cache_minutes} мин")
        return True
    except Exception as e:
        logger.error(f"Ошибка проверки токена: {e}")
        return False


if not asyncio.run(check_bot_token()):
    print("Проверьте BOT_TOKEN в .env!")
    exit(1)


# Создаем бота и диспетчер
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()


# Время кэширования в минутах
cache_minutes = CACHE_EXPIRE / 60


# Начальное сообщение при запуске бота
start_txt = f"""
🌤️ *Прогноз погоды*

Отправьте название города.
"""

# Сообщение помощи
help_txt = f"""
• /start - запуск бота
• /help - справка

Для получения информации о погоде напишите название города.

Данные предоставлены OpenWeatherMap API. Запросы кэшируются на {cache_minutes:.0f} мин. 
"""


@dp.message(CommandStart())
async def start_handler(message: Message):
    """Обработчик команды /start"""
    await message.answer(start_txt)


@dp.message(Command('help'))
async def help_handler(message: Message):
    """Обработчик команды /help"""
    await message.answer(help_txt)


@dp.message(F.text)
async def get_weather(message: Message):
    """Обработчик текстовых сообщений и получение погоды"""
    city = message.text.strip()

    if city.lower() in ['start', 'help']:
        return

    # Временное сообщение загрузки
    loading_msg = await message.answer(f"🔍 Ищу погоду для *{city}*...")

    try:  # Получаем данные о погоде с openweather
        url = f'https://api.openweathermap.org/data/2.5/weather?q={city}&units=metric&lang=ru&appid={WEATHER_API_KEY}'
        response = requests.get(url, timeout=10)
        weather_data = response.json()

        if response.status_code != 200:
            error_msg = f"Город не найден!"
            if 'message' in weather_data:
                error_msg += f"\n💡 {weather_data['message']}"
            await loading_msg.edit_text(error_msg)
            return

        # Извлекаем данные
        main = weather_data['main']
        weather = weather_data['weather'][0]
        wind = weather_data['wind']
        sys_info = weather_data['sys']

        temperature = round(main['temp'])
        feels_like = round(main['feels_like'])
        humidity = main['humidity']
        description = weather['description'].capitalize()
        wind_speed = round(wind.get('speed', 0))
        wind_gust = round(wind.get('gust', 0))
        pressure = round(main['pressure'] * 0.75006)
        sunrise = datetime.fromtimestamp(sys_info['sunrise']).strftime('%H:%M')
        sunset = datetime.fromtimestamp(sys_info['sunset']).strftime('%H:%M')

        gust_text = f" (порывы до {wind_gust} м/с)" if wind_gust > wind_speed else ""

        # Статус кэша
        from_cache = isinstance(response, CachedResponse) and getattr(response, 'from_cache', False)
        cache_status = " 📁 (из кэша)" if from_cache else " 🌐 (обновлено)"

        # формируем текст для отправки
        weather_msg = f"""
🌤️ *Погода в {city.title()}* {cache_status}

🌡️ *{temperature}°C* (ощущается как {feels_like}°C) — {description}

💧 Влажность: {humidity}%
🌪 Ветер: {wind_speed} м/с {gust_text}
📊 Давление: {pressure} мм рт. ст.

🌅 Рассвет: {sunrise}
🌇 Закат: {sunset}

*Обновлено:* {datetime.now().strftime('%H:%M %d.%m.%Y')}
""".strip()

        await loading_msg.edit_text(weather_msg)

    except requests.exceptions.RequestException:
        await loading_msg.edit_text("Нет интернета (используется кэш). Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в get_weather: {e}")
        await loading_msg.edit_text("Произошла ошибка. Попробуйте другой город.")


async def main():
    """Основной цикл бота"""
    logger.info(f"Бот запускается с кэшем {cache_minutes:.0f} мин")
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(10)


if __name__ == '__main__':
    asyncio.run(main())
