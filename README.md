# YouTube to MP3 Telegram Bot

Telegram бот на Aiogram 3.x для конвертации YouTube видео в аудио (M4A).

## Возможности

- Скачивание аудио из YouTube по ссылке
- Поиск видео по названию (YouTube Data API v3 + fallback на yt-dlp)
- Распознавание трека по голосовому сообщению через Shazam
- Рассылка `/broadcast` (только для админов)
- Статистика `/stats` (только для админов)
- Ограничение длительности видео (до 30 минут)
- Автоматическая очистка файлов после отправки

## Требования

- Python 3.11+
- FFmpeg (только для локального запуска без Docker)
- Docker + Docker Compose (рекомендуется для прода)

## Поддерживаемые платформы

| Платформа              | Способ запуска                     | Wheels shazamio-core |
|------------------------|------------------------------------|----------------------|
| macOS arm64 (M1/M2/M3) | venv или Docker (linux/arm64)      | ✅ есть              |
| Linux x86_64 (сервер)  | Docker (linux/amd64)               | ✅ есть              |
| Linux aarch64          | Docker (linux/arm64)               | ✅ есть              |

> Поскольку для всех целевых платформ опубликованы prebuilt wheels на PyPI,
> Rust toolchain устанавливать не нужно — `pip install` справится сам.

## Установка

### Локально (macOS / Linux)

1. Клонировать репозиторий и установить FFmpeg:
   ```bash
   # macOS (M1/M2/M3)
   brew install ffmpeg

   # Linux (Debian/Ubuntu)
   sudo apt-get install ffmpeg
   ```

2. Создать виртуальное окружение и установить зависимости:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Создать `.env`:
   ```bash
   cp .env.example .env
   # отредактируй BOT_TOKEN, ADMIN_USER_IDS, YOUTUBE_API_KEY
   ```

4. Запустить:
   ```bash
   python main.py
   ```

### Docker (M3 Pro локально / сервер)

Multi-stage Dockerfile собирает образ под текущую архитектуру хоста (`linux/arm64` на M3 Pro, `linux/amd64` на сервере). FFmpeg уже включён в образ.

```bash
# .env должен существовать
docker compose up -d --build

# логи
docker logs youtomp3-bot -f

# рестарт после изменения кода (volume монтирован)
docker compose restart

# полная пересборка
./rebuild.sh
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
