#!/bin/bash
echo "Останавливаю контейнеры..."
docker-compose down

echo "Пересобираю Docker образ (--no-cache для чистой сборки)..."
docker-compose build --no-cache

echo "Запускаю контейнеры..."
docker-compose up -d

echo "Показываю логи (Ctrl+C для выхода)..."
docker-compose logs -f
