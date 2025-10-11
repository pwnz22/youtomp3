# YouTube to MP3 Telegram Bot

Telegram бот на Aiogram 3.x для конвертации YouTube видео в MP3 файлы.

## Возможности

- Конвертация YouTube видео в MP3 (320 kbps)
- Ограничение длительности видео (до 30 минут)
- Автоматическая очистка файлов после отправки
- Простой интерфейс через Telegram

## Требования

- Python 3.11+
- FFmpeg
- Docker (для контейнеризации)

## Установка

### Локально

1. Клонируйте репозиторий
2. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте `.env` файл:
```bash
cp .env.example .env
```

5. Добавьте токен бота в `.env`:
```
BOT_TOKEN=your_bot_token_here
```

6. Запустите бота:
```bash
python main.py
```

### С Docker

1. Создайте `.env` файл с токеном бота

2. Соберите образ:
```bash
docker build -t youtomp3-bot .
```

3. Запустите контейнер:
```bash
docker run -d --name youtomp3-bot --env-file .env youtomp3-bot
```

Или используйте docker-compose:
```bash
docker-compose up -d
```

## Использование

1. Найдите бота в Telegram
2. Отправьте команду `/start`
3. Отправьте ссылку на YouTube видео
4. Получите MP3 файл

## Структура проекта

```
youtomp3/
├── app/
│   ├── __init__.py
│   ├── bot.py              # Инициализация бота
│   ├── config.py           # Конфигурация
│   ├── handlers.py         # Обработчики команд
│   └── services/
│       ├── __init__.py
│       └── youtube.py      # YouTube сервис
├── main.py                 # Точка входа
├── requirements.txt        # Зависимости
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── .gitignore
```

## Лицензия

MIT
