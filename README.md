# Kotocode Bot — инструкция по деплою

## 1. Подготовка VPS (Ubuntu 22.04)

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip git

# Создание пользователя для бота
sudo useradd -m -s /bin/bash kotocode
sudo su - kotocode
```

## 2. Загрузка кода

```bash
# Находясь под пользователем kotocode
cd ~
git clone <ваш репозиторий> kotocode-bot
# ИЛИ загрузите файлы через scp/SFTP
```

## 3. Виртуальное окружение и зависимости

```bash
cd ~/kotocode-bot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Настройка .env

```bash
cp .env.example .env
nano .env
```

Заполнить:
- `BOT_TOKEN` — токен от @BotFather
- `GENERAL_CHAT_ID` — ID группового чата (добавить @userinfobot в группу)
- `SUPERADMIN_ID` — ваш Telegram ID (узнать у @userinfobot)

## 5. Создание директорий

```bash
mkdir -p data logs
```

## 6. Тест запуска

```bash
source venv/bin/activate
python main.py
# Ctrl+C для остановки
```

## 7. Настройка systemd

```bash
# Выйти из пользователя kotocode
exit

# Скопировать unit-файл
sudo cp /home/kotocode/kotocode-bot/systemd/kotocode-bot.service /etc/systemd/system/

# Активировать и запустить
sudo systemctl daemon-reload
sudo systemctl enable kotocode-bot
sudo systemctl start kotocode-bot

# Проверить статус
sudo systemctl status kotocode-bot
```

## 8. Просмотр логов

```bash
# Логи systemd (в реальном времени)
sudo journalctl -u kotocode-bot -f

# Логи файла
tail -f /home/kotocode/kotocode-bot/logs/bot.log
```

## 9. Перезапуск после обновления кода

```bash
sudo systemctl restart kotocode-bot
```

## 10. Первый запуск бота

1. Напиши боту `/start` — бот зарегистрирует тебя как супер-админа
2. Добавь администраторов: `/addadmin @username`
3. Добавь менеджеров: `/addmanager @username`
4. Добавь преподавателей: `/addteacher @username`
5. Добавь бота в общий чат группы и дай права администратора

## Узнать ID чата

Добавь `@userinfobot` в группу — он напишет ID группы.
Или перешли любое сообщение из группы боту @userinfobot.
