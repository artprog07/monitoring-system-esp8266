import asyncio
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from telethon import TelegramClient
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, GROUP_CHAT_ID, BOT_TOKEN
from db import get_connection, save_sensor_reading

# Эти значения нужно добавить в config.py или .env-логику.
# Взять можно на https://my.telegram.org/apps
try:
    from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE
except ImportError:
    TELEGRAM_API_ID = None
    TELEGRAM_API_HASH = None
    TELEGRAM_PHONE = None

SESSION_NAME = "esp_cache_reader"
DEFAULT_STATION = "ESP8266_001"


def send_main_bot_notification(chat_id, text):
    try:
        url = "https://api.telegram.org/bot" + str(BOT_TOKEN) + "/sendMessage"
        data = urllib.parse.urlencode({"chat_id": str(chat_id), "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            result = response.read().decode("utf-8", errors="ignore")
        print(f"Уведомление отправлено в основной бот: chat_id={chat_id}")
        return True
    except Exception as e:
        print("Ошибка отправки уведомления в основной бот:", e)
        return False

def ensure_sync_tables():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS TelegramSyncState (
                chat_id VARCHAR(100) PRIMARY KEY,
                last_message_id INT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS TelegramProcessedMessages (
                chat_id VARCHAR(100) NOT NULL,
                message_id INT NOT NULL,
                station_serial VARCHAR(100),
                raw_text TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, message_id)
            )
        """)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка создания sync-таблиц:", e)
    finally:
        cur.close()
        conn.close()

def get_last_message_id(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT last_message_id FROM TelegramSyncState WHERE chat_id=%s", (str(chat_id),))
        row = cur.fetchone()
        if row:
            return row[0] or 0
        cur.execute("INSERT INTO TelegramSyncState (chat_id,last_message_id) VALUES (%s,0)", (str(chat_id),))
        conn.commit()
        return 0
    except Exception as e:
        conn.rollback()
        print("Ошибка чтения last_message_id:", e)
        return 0
    finally:
        cur.close()
        conn.close()

def set_last_message_id(chat_id, message_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO TelegramSyncState (chat_id,last_message_id,updated_at)
            VALUES (%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (chat_id)
            DO UPDATE SET last_message_id=EXCLUDED.last_message_id, updated_at=CURRENT_TIMESTAMP
        """, (str(chat_id), int(message_id)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка обновления last_message_id:", e)
    finally:
        cur.close()
        conn.close()

def mark_processed(chat_id, message_id, station_serial, raw_text):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO TelegramProcessedMessages (chat_id,message_id,station_serial,raw_text,processed_at)
            VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (chat_id,message_id) DO NOTHING
        """, (str(chat_id), int(message_id), station_serial, raw_text))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка записи processed message:", e)
    finally:
        cur.close()
        conn.close()

def parse_esp_message(text):
    if not text:
        return None
    original = text.strip()
    normalized = original.replace(";", ",").replace("\n", ",")
    parts = [p.strip() for p in normalized.split(",") if p.strip()]
    data = {}
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
        elif ":" in part:
            key, value = part.split(":", 1)
        else:
            continue
        key = key.strip().lower()
        value = value.strip()
        data[key] = value

    station = (
        data.get("station")
        or data.get("esp")
        or data.get("serial")
        or data.get("station_serial")
        or data.get("станция")
    )

    if not station:
        for part in parts:
            if re.fullmatch(r"[A-Za-z0-9]+(?:[A-Za-z0-9\\-]*)?_\\d{3}", part.strip()):
                station = part.strip()
                break

    if not station:
        station = DEFAULT_STATION

    source_type = data.get("event") or data.get("source") or data.get("type") or "auto"

    aliases = {
        "temp": "temperature",
        "t": "temperature",
        "температура": "temperature",
        "temperature": "temperature",
        "hum": "humidity",
        "h": "humidity",
        "влажность": "humidity",
        "humidity": "humidity",
        "press": "pressure",
        "p": "pressure",
        "давление": "pressure",
        "pressure": "pressure",
        "light": "light",
        "lux": "light",
        "освещенность": "light",
        "освещённость": "light",
        "co2": "co2",
        "co₂": "co2"
    }

    readings = {}
    for key, value in data.items():
        category = aliases.get(key)
        if not category:
            continue
        try:
            readings[category] = float(value.replace(",", "."))
        except ValueError:
            pass

    if not readings:
        return None

    return station.strip(), readings, source_type.strip()


def source_title(source_type):
    names = {
        "auto": "автоматическая отправка",
        "manual_web": "веб-интерфейс станции",
        "manual_lcd": "локальное меню станции"
    }
    return names.get(source_type, source_type)


def category_title(category):
    names = {
        "temperature": "Температура",
        "humidity": "Влажность",
        "pressure": "Давление",
        "light": "Освещённость",
        "co2": "CO2"
    }
    return names.get(category, category)


def category_unit(category):
    units = {
        "temperature": "°C",
        "humidity": "%",
        "pressure": "hPa",
        "light": "lx",
        "co2": "ppm"
    }
    return units.get(category, "")


def format_readings_text(readings):
    lines = []
    order = ["temperature", "humidity", "pressure", "light", "co2"]

    for category in order:
        if category in readings:
            unit = category_unit(category)
            value = readings[category]
            lines.append(f"{category_title(category)}: {value:g} {unit}".rstrip())

    for category, value in readings.items():
        if category not in order:
            unit = category_unit(category)
            lines.append(f"{category_title(category)}: {value:g} {unit}".rstrip())

    return "\n".join(lines)


def prettify_alert(alert):
    text = str(alert)
    replacements = {
        "temperature": "температура",
        "humidity": "влажность",
        "pressure": "давление",
        "light": "освещённость",
        "co2": "CO2"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace("Показатель ", "")
    return text


def format_manual_notification(station_name, station_serial, source_type, readings):
    return (
        "Показания получены вручную\n\n"
        f"Станция: {station_name}\n"
        f"Серийный номер: {station_serial}\n"
        f"Источник: {source_title(source_type)}\n\n"
        f"{format_readings_text(readings)}"
    )


def format_alert_notification(station_name, station_serial, alerts):
    alert_text = "\n".join(f"- {prettify_alert(alert)}" for alert in alerts)
    return (
        "Предупреждение по показаниям\n\n"
        f"Станция: {station_name}\n"
        f"Серийный номер: {station_serial}\n\n"
        f"{alert_text}"
    )


def ensure_station_offline_columns():
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("ALTER TABLE Stations ADD COLUMN IF NOT EXISTS offline_notified BOOLEAN DEFAULT FALSE")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка обновления Stations для offline_notified:", e)
    finally:
        cur.close()
        conn.close()


def get_offline_stations(minutes_limit=3):
    ensure_station_offline_columns()
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT s.station_id,s.station_name,s.serial_number,s.last_seen,u.telegram_id
            FROM Stations s
            JOIN Users u ON s.user_id=u.user_id
            WHERE s.is_active=TRUE
              AND s.last_seen IS NOT NULL
              AND s.offline_notified=FALSE
              AND s.last_seen < NOW() - (%s || ' minutes')::INTERVAL
        """, (minutes_limit,))
        rows = cur.fetchall()
        return rows
    finally:
        cur.close()
        conn.close()


def mark_station_offline_notified(station_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("UPDATE Stations SET offline_notified=TRUE WHERE station_id=%s", (station_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка обновления offline_notified:", e)
    finally:
        cur.close()
        conn.close()


def reset_station_offline_flag(station_serial):
    ensure_station_offline_columns()
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("UPDATE Stations SET offline_notified=FALSE WHERE serial_number=%s", (station_serial,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Ошибка сброса offline_notified:", e)
    finally:
        cur.close()
        conn.close()


def format_offline_notification(station_name, station_serial, last_seen, minutes_limit):
    last_seen_text = last_seen.strftime("%d.%m.%Y %H:%M:%S") if last_seen else "нет данных"

    return (
        "Станция не передает данные\n\n"
        f"Станция: {station_name}\n"
        f"Серийный номер: {station_serial}\n"
        f"Последние данные: {last_seen_text}\n\n"
        f"Показания не поступают больше {minutes_limit} мин."
    )


def check_offline_stations(minutes_limit=3):
    rows = get_offline_stations(minutes_limit)

    for station_id, station_name, station_serial, last_seen, telegram_id in rows:
        send_main_bot_notification(
            telegram_id,
            format_offline_notification(station_name, station_serial, last_seen, minutes_limit)
        )
        mark_station_offline_notified(station_id)
        print(f"Уведомление об отключении станции отправлено: {station_serial}")

async def process_message(message):
    text = message.message or ""
    parsed = parse_esp_message(text)
    if not parsed:
        return False
    station_serial, readings, source_type = parsed
    saved = 0
    alerts = []
    notify_user_id = None
    notify_chat_id = None
    station_name = station_serial

    for category, value in readings.items():
        ok, msg = save_sensor_reading(
            station_serial,
            category,
            value,
            source_type=source_type,
            telegram_message_id=message.id,
            recorded_at=(message.date.replace(tzinfo=None) + timedelta(hours=3)) if message.date else None
        )
        if ok:
            saved += 1
            if isinstance(msg, dict):
                notify_user_id = msg.get("user_id") or notify_user_id
                notify_chat_id = msg.get("telegram_id") or notify_chat_id
                station_name = msg.get("station_name") or station_name
                if msg.get("alert"):
                    alerts.append(msg.get("alert"))
        else:
            print(f"Не сохранено: station={station_serial}, category={category}, value={value}. Причина: {msg}")

    mark_processed(GROUP_CHAT_ID, message.id, station_serial, text)

    if saved:
        print(f"[OK] message_id={message.id}, station={station_serial}, source={source_type}, saved={saved}")

        if notify_chat_id and source_type in ["manual_web", "manual_lcd"]:
            send_main_bot_notification(
                notify_chat_id,
                format_manual_notification(station_name, station_serial, source_type, readings)
            )

        if notify_chat_id and alerts:
            send_main_bot_notification(
                notify_chat_id,
                f"Предупреждение по станции {station_name} ({station_serial}):\n" + "\n".join(alerts)
            )

        return True

    print(f"[SKIP] message_id={message.id}, station={station_serial}, source={source_type}, readings_found={len(readings)}, saved=0")
    return False

async def sync_once():
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH or not TELEGRAM_PHONE:
        print("Добавь TELEGRAM_API_ID, TELEGRAM_API_HASH и TELEGRAM_PHONE в config.py")
        return

    ensure_sync_tables()

    client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await client.start(phone=TELEGRAM_PHONE)

    chat_id = int(GROUP_CHAT_ID)
    last_id = get_last_message_id(chat_id)
    print(f"Старт синхронизации. chat_id={chat_id}, last_message_id={last_id}")

    count_total = 0
    count_processed = 0
    newest_id = last_id

    async for message in client.iter_messages(chat_id, min_id=last_id, reverse=True):
        if not message.message:
            continue
        count_total += 1
        ok = await process_message(message)
        newest_id = max(newest_id, message.id)
        if ok:
            count_processed += 1
        set_last_message_id(chat_id, newest_id)

    print(f"Готово. Новых сообщений просмотрено: {count_total}. Обработано как ESP-данные: {count_processed}. last_message_id={newest_id}")
    await client.disconnect()

async def sync_forever(delay_seconds=30):
    while True:
        try:
            await sync_once()
        except Exception as e:
            print("Ошибка sync_forever:", e)
        await asyncio.sleep(delay_seconds)

if __name__ == "__main__":
    # Постоянный режим: каждые 60 секунд проверяет группу и забирает новые сообщения.
    asyncio.run(sync_forever(30))
