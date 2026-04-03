# YouTubeToMP3 Bot

Telegram-бот для скачивания аудио из YouTube видео с поиском и рассылкой.

## Stack

- **Python 3.11+**
- **aiogram 3.x** — Telegram Bot Framework (FSM для диалогов)
- **yt-dlp** — скачивание и конвертация YouTube видео
- **SQLAlchemy 2.0** (async) — ORM
- **aiosqlite** — асинхронный SQLite драйвер
- **FFmpeg** — извлечение аудио
- **Docker** — контейнеризация

## Architecture

```
youtomp3/
├── CLAUDE.md                # Конвенции проекта
├── SPEC.md                  # Спецификация функциональности
├── CHANGELOG.md             # История изменений по версиям
├── VERSION                  # Текущая версия (SemVer)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── main.py                  # Точка входа
├── app/
│   ├── bot.py               # Инициализация бота и диспетчера
│   ├── config.py            # Конфигурация из .env
│   ├── database.py          # Сервис работы с БД
│   ├── models.py            # SQLAlchemy модели
│   ├── handlers.py          # Обработчики команд и сообщений
│   └── services/
│       └── youtube.py       # YouTube сервис (скачивание, поиск)
└── data/
    └── bot.db               # SQLite база (создаётся автоматически)
```

## Conventions

### Python
- Async код: никаких синхронных блокирующих вызовов в хендлерах
- Type hints для аргументов функций и возвращаемых значений
- Именование: snake_case для функций/переменных, PascalCase для классов

### aiogram
- FSM для многоступенчатых диалогов (broadcast)
- Inline-клавиатуры для интерактивных списков
- Dependency injection через `dp.workflow_data`

### SQLAlchemy
- Только async: `async_sessionmaker`, `AsyncSession`
- Модели: User, Download, Error

## Versioning

**Semantic Versioning (SemVer)**: `MAJOR.MINOR.PATCH`

- **MAJOR** — несовместимые изменения
- **MINOR** — новая функциональность
- **PATCH** — багфиксы

### Файлы версионирования
- `VERSION` — текущая версия (одна строка)
- `CHANGELOG.md` — описание изменений каждой версии
- Git tags — каждый релиз получает тег `v0.x.0`

### Процесс релиза
1. Обновить `VERSION` и `CHANGELOG.md`
2. Коммит: `release: v0.x.0`
3. Создать тег: `git tag v0.x.0`
4. Push с тегами: `git push --tags`

## Commit Guidelines
- Формат: `type: описание на русском`
- Типы: `feat`, `fix`, `refactor`, `docs`, `chore`, `release`
- Одна строка, без длинных описаний
- Без указания авторства

## Spec-first подход
- Перед началом нового функционала — описать в `SPEC.md`
- Каждая версия = набор фич из спецификации
- После реализации — отметить `[x]` в SPEC.md и обновить CHANGELOG.md

## Commands

```bash
# Локальный запуск
python main.py

# Docker
docker compose up -d --build

# Рестарт после изменений кода (volume монтирован)
docker compose restart

# Логи
docker logs youtomp3-bot -f

# Текущая версия
cat VERSION
```

## Important
- НИКОГДА не запускай миграции (`alembic upgrade head`)
- НИКОГДА не коммить без запроса пользователя
- `.env` файл НЕ коммитить
- При добавлении новых env-переменных — обновлять `.env.example`
