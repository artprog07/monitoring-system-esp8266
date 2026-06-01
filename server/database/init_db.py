import psycopg2
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST
try:
    from config import DB_PORT
except ImportError:
    DB_PORT = "5432"
from datetime import datetime
import pandas as pd
import os
def autofit_excel_columns(filename):
    try:
        from openpyxl import load_workbook
        wb=load_workbook(filename)
        for ws in wb.worksheets:
            for column_cells in ws.columns:
                max_length=0
                column_letter=column_cells[0].column_letter
                for cell in column_cells:
                    value=cell.value
                    if value is None:
                        continue
                    if hasattr(value,"strftime"):
                        value=value.strftime("%d.%m.%Y %H:%M:%S")
                    max_length=max(max_length,len(str(value)))
                ws.column_dimensions[column_letter].width=min(max_length+3,40)
        wb.save(filename)
    except Exception as e:
        print(e)
def get_connection():
    return psycopg2.connect(dbname=DB_NAME,user=DB_USER,password=DB_PASSWORD,host=DB_HOST,port=DB_PORT)
def column_exists(table_name,column_name):
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE lower(table_name)=lower(%s) AND lower(column_name)=lower(%s)
            LIMIT 1
        """,(table_name,column_name))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()
def update_user_username(telegram_id,username):
    if not username or not column_exists("Users","username"):
        return
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("UPDATE Users SET username=%s WHERE telegram_id=%s",(username,str(telegram_id)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
    finally:
        cur.close()
        conn.close()
def get_user_by_username(username):
    username=(username or "").strip()
    if username.startswith("@"):
        username=username[1:]
    if not username or not column_exists("Users","username"):
        return None
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("SELECT user_id,full_name,telegram_id,phone_number,email,registered_at FROM Users WHERE lower(username)=lower(%s)",(username,))
        row=cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()
def log_user_action(user_id,station_id,action_type,value=1,status="completed"):
    if not user_id or not station_id:
        return False
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("SELECT type_id FROM InteractionTypes WHERE type_name=%s LIMIT 1",(action_type,))
        row=cur.fetchone()
        if row:
            interaction_type_id=row[0]
        else:
            cur.execute("INSERT INTO InteractionTypes (type_name,description) VALUES (%s,%s) RETURNING type_id",(action_type,action_type))
            interaction_type_id=cur.fetchone()[0]
        cur.execute("""
            INSERT INTO UserInteraction (station_id,user_id,value,interaction_type_id,timestamp,status)
            VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP,%s)
        """,(station_id,user_id,value,interaction_type_id,status))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(e)
        return False
    finally:
        cur.close()
        conn.close()
def ensure_activity_log_table():
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS UserActivityLog (
                activity_id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                action_type VARCHAR(100) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_user_activity_user
                FOREIGN KEY (user_id)
                REFERENCES Users(user_id)
                ON DELETE CASCADE
            )
        """)
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(e)
        return False
    finally:
        cur.close()
        conn.close()
def log_user_activity(user_id,action_type,description=None):
    if not user_id:
        return False
    ensure_activity_log_table()
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            INSERT INTO UserActivityLog (user_id,action_type,description,created_at)
            VALUES (%s,%s,%s,CURRENT_TIMESTAMP)
        """,(user_id,action_type,description))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(e)
        return False
    finally:
        cur.close()
        conn.close()

def ensure_sensor_readings_metadata():
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("ALTER TABLE SensorReadings ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)")
        cur.execute("ALTER TABLE SensorReadings ADD COLUMN IF NOT EXISTS telegram_message_id INT")
        cur.execute("ALTER TABLE SensorReadings ADD COLUMN IF NOT EXISTS is_limit_alert BOOLEAN DEFAULT FALSE")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(e)
        return False
    finally:
        cur.close()
        conn.close()
def init_sensor_types():
    ensure_activity_log_table()
    ensure_sensor_readings_metadata()
    default_types=[
        ("Температура","°C","temperature"),
        ("Влажность","%","humidity"),
        ("Давление","hPa","pressure"),
        ("Освещённость","lx","light"),
        ("CO2","ppm","co2")
    ]
    conn=get_connection()
    cur=conn.cursor()
    try:
        for type_name,unit,category in default_types:
            cur.execute("SELECT sensor_type_id FROM SensorTypes WHERE category=%s LIMIT 1",(category,))
            row=cur.fetchone()
            if not row:
                cur.execute("INSERT INTO SensorTypes (type_name,unit,category) VALUES (%s,%s,%s)",(type_name,unit,category))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(e)
        return False
    finally:
        cur.close()
        conn.close()
def get_users():
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT user_id,full_name,telegram_id FROM Users ORDER BY user_id")
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_all_users_for_admin():
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT user_id,full_name,telegram_id,phone_number,email,registered_at FROM Users ORDER BY user_id")
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_user_by_telegram(telegram_id):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT user_id,full_name,telegram_id,phone_number,email,registered_at FROM Users WHERE telegram_id=%s",(str(telegram_id),))
    row=cur.fetchone()
    cur.close()
    conn.close()
    return row
def get_user_by_id(user_id):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT user_id,full_name,telegram_id,phone_number,email,registered_at FROM Users WHERE user_id=%s",(user_id,))
    row=cur.fetchone()
    cur.close()
    conn.close()
    return row
def register_user(telegram_id,full_name,phone_number,email,username=None):
    conn=get_connection()
    cur=conn.cursor()
    try:
        if username and column_exists("Users","username"):
            cur.execute("""
                INSERT INTO Users (username,telegram_id,full_name,phone_number,email,registered_at)
                VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                RETURNING user_id
            """,(username,str(telegram_id),full_name,phone_number,email))
        else:
            cur.execute("""
                INSERT INTO Users (telegram_id,full_name,phone_number,email,registered_at)
                VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)
                RETURNING user_id
            """,(str(telegram_id),full_name,phone_number,email))
        user_id=cur.fetchone()[0]
        conn.commit()
        return user_id,"Регистрация успешно завершена"
    except Exception as e:
        conn.rollback()
        return None,f"Ошибка регистрации: {e}"
    finally:
        cur.close()
        conn.close()
def update_user_profile(telegram_id,field,value):
    allowed_fields={"full_name","phone_number","email"}
    if field not in allowed_fields:
        return False,"Недопустимое поле профиля"
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute(f"UPDATE Users SET {field}=%s WHERE telegram_id=%s",(value,str(telegram_id)))
        if cur.rowcount==0:
            conn.rollback()
            return False,"Пользователь не найден"
        conn.commit()
        return True,"Профиль обновлён"
    except Exception as e:
        conn.rollback()
        return False,f"Ошибка обновления профиля: {e}"
    finally:
        cur.close()
        conn.close()
def get_user_stations(user_id):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT station_id,station_name,serial_number,locations
        FROM Stations
        WHERE user_id=%s
        ORDER BY station_id
    """,(user_id,))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_stations():
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT s.station_id,s.station_name,s.serial_number,s.locations,u.full_name
        FROM Stations s
        JOIN Users u ON s.user_id=u.user_id
        ORDER BY s.station_id
    """)
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def add_station(name,serial,location,user_id):
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            INSERT INTO Stations (station_name,serial_number,locations,user_id,installed_at,is_active,last_seen)
            VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP,TRUE,NULL)
            RETURNING station_id
        """,(name,serial,location,user_id))
        station_id=cur.fetchone()[0]
        conn.commit()
        log_user_action(user_id,station_id,"add_station")
        log_user_activity(user_id,"add_station",f"Добавлена станция {name} ({serial})")
        return True,f"Станция «{name}» успешно добавлена."
    except Exception as e:
        conn.rollback()
        return False,f"Ошибка добавления станции: {e}"
    finally:
        cur.close()
        conn.close()
def delete_station(station_id):
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("SELECT user_id,station_name FROM Stations WHERE station_id=%s",(station_id,))
        station_info=cur.fetchone()
        cur.execute("DELETE FROM Stations WHERE station_id=%s",(station_id,))
        if cur.rowcount==0:
            conn.rollback()
            return "Станция не найдена."
        conn.commit()
        if station_info:
            log_user_activity(station_info[0],"delete_station",f"Удалена станция {station_info[1]}")
        return f"Станция с ID {station_id} удалена."
    except Exception as e:
        conn.rollback()
        return f"Ошибка удаления станции: {e}"
    finally:
        cur.close()
        conn.close()
def delete_user(user_id):
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("DELETE FROM Users WHERE user_id=%s",(user_id,))
        if cur.rowcount==0:
            conn.rollback()
            return "Пользователь не найден."
        conn.commit()
        return f"Пользователь с ID {user_id} удалён."
    except Exception as e:
        conn.rollback()
        return f"Ошибка удаления пользователя: {e}"
    finally:
        cur.close()
        conn.close()
def get_sensor_types():
    init_sensor_types()
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT sensor_type_id,type_name,unit,category FROM SensorTypes ORDER BY sensor_type_id")
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_sensors_by_station(station_id):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT ss.station_sensor_id,ss.sensor_model,st.category,st.unit,ss.min_value,ss.max_value,ss.is_active
        FROM StationSensors ss
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        WHERE ss.station_id=%s
        ORDER BY ss.station_sensor_id
    """,(station_id,))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def add_station_sensor(station_id,category,sensor_model,min_value,max_value):
    init_sensor_types()
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("SELECT sensor_type_id FROM SensorTypes WHERE category=%s LIMIT 1",(category,))
        row=cur.fetchone()
        if not row:
            conn.rollback()
            return False,"Тип датчика не найден."
        sensor_type_id=row[0]
        cur.execute("""
            INSERT INTO StationSensors (station_id,sensor_type_id,sensor_model,is_active,min_value,max_value,installed_date)
            VALUES (%s,%s,%s,1,%s,%s,CURRENT_TIMESTAMP)
        """,(station_id,sensor_type_id,sensor_model,min_value,max_value))
        cur.execute("SELECT user_id FROM Stations WHERE station_id=%s",(station_id,))
        user_row=cur.fetchone()
        conn.commit()
        if user_row:
            log_user_action(user_row[0],station_id,"add_sensor")
            log_user_activity(user_row[0],"add_sensor",f"Добавлен датчик {sensor_model}")
        return True,f"Датчик «{sensor_model}» добавлен."
    except Exception as e:
        conn.rollback()
        return False,f"Ошибка добавления датчика: {e}"
    finally:
        cur.close()
        conn.close()
def delete_station_sensor(station_sensor_id):
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            SELECT ss.station_id,s.user_id
            FROM StationSensors ss
            JOIN Stations s ON ss.station_id=s.station_id
            WHERE ss.station_sensor_id=%s
        """,(station_sensor_id,))
        info=cur.fetchone()
        cur.execute("DELETE FROM StationSensors WHERE station_sensor_id=%s",(station_sensor_id,))
        if cur.rowcount==0:
            conn.rollback()
            return "Датчик не найден."
        conn.commit()
        if info:
            log_user_action(info[1],info[0],"delete_sensor")
            log_user_activity(info[1],"delete_sensor","Удалён датчик")
        return "Датчик удалён."
    except Exception as e:
        conn.rollback()
        return f"Ошибка удаления датчика: {e}"
    finally:
        cur.close()
        conn.close()
def get_sensor_readings_for_user(user_id,days):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        WHERE s.user_id=%s AND sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
        ORDER BY sr.recorded_at DESC
    """,(user_id,days))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_sensor_readings_for_admin(days):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT u.full_name,s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        JOIN Users u ON s.user_id=u.user_id
        WHERE sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
        ORDER BY sr.recorded_at DESC
    """,(days,))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_sensor_readings_for_user_date(user_id,target_date):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        WHERE s.user_id=%s AND DATE(sr.recorded_at)=%s
        ORDER BY sr.recorded_at ASC
    """,(user_id,target_date))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_sensor_readings_for_admin_date(target_date):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT u.full_name,s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        JOIN Users u ON s.user_id=u.user_id
        WHERE DATE(sr.recorded_at)=%s
        ORDER BY sr.recorded_at ASC
    """,(target_date,))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows

def source_label_db(source):
    labels={
        "auto":"автоматическая отправка",
        "manual_lcd":"ручная отправка с меню станции",
        "manual_web":"ручная отправка с веб-интерфейса",
        None:"старые данные",
        "None":"старые данные",
        "":"старые данные"
    }
    return labels.get(source,str(source))


def prepare_readings_dataframe(rows,user_id):
    if user_id is None:
        data=[]
        for r in rows:
            data.append([
                r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],
                source_label_db(r[8] if len(r)>8 else None),
                "превышен" if len(r)>9 and r[9] else "норма"
            ])
        return pd.DataFrame(data,columns=["Пользователь","Станция","Модель датчика","Тип","Категория","Ед. изм.","Значение","Время","Источник","Лимит"])
    data=[]
    for r in rows:
        data.append([
            r[0],r[1],r[2],r[3],r[4],r[5],r[6],
            source_label_db(r[7] if len(r)>7 else None),
            "превышен" if len(r)>8 and r[8] else "норма"
        ])
    return pd.DataFrame(data,columns=["Станция","Модель датчика","Тип","Категория","Ед. изм.","Значение","Время","Источник","Лимит"])



def category_column_label(category, unit):
    names={
        "temperature":"Температура",
        "humidity":"Влажность",
        "pressure":"Давление",
        "light":"Освещенность",
        "co2":"CO2"
    }
    title=names.get(str(category),str(category))
    return f"{title}, {unit}" if unit else title


def source_label_short(source):
    labels={
        "auto":"автоматически",
        "manual_lcd":"ручная отправка с меню станции",
        "manual_web":"ручная отправка с веб-интерфейса",
        None:"не указан",
        "None":"не указан",
        "":"не указан"
    }
    return labels.get(source,str(source))


def build_user_wide_report(rows):
    sensor_info=[]
    seen_sensors=set()

    for r in rows:
        station_name,sensor_model,type_name,category,unit,value,recorded_at,source_type,is_limit_alert,telegram_message_id=r
        key=(category,sensor_model,type_name,unit)

        if key not in seen_sensors:
            seen_sensors.add(key)
            sensor_info.append({
                "Параметр": category_column_label(category,unit),
                "Модель датчика": sensor_model,
                "Тип датчика": type_name,
                "Ед. изм.": unit
            })

    grouped={}

    for r in rows:
        station_name,sensor_model,type_name,category,unit,value,recorded_at,source_type,is_limit_alert,telegram_message_id=r

        if telegram_message_id is not None:
            group_key=("msg",telegram_message_id)
        else:
            group_key=("time",recorded_at.replace(second=0,microsecond=0))

        if group_key not in grouped:
            grouped[group_key]={
                "Дата и время": recorded_at.replace(microsecond=0),
                "Станция": station_name,
                "Источник": source_label_short(source_type),
                "Лимит": "норма"
            }

        col=category_column_label(category,unit)
        grouped[group_key][col]=value

        if is_limit_alert:
            grouped[group_key]["Лимит"]="превышен"

        if grouped[group_key]["Источник"]=="не указан":
            grouped[group_key]["Источник"]=source_label_short(source_type)

    table_rows=list(grouped.values())
    table_rows.sort(key=lambda x:x["Дата и время"],reverse=True)

    sensor_df=pd.DataFrame(sensor_info)

    value_columns=[]
    for item in sensor_info:
        col=item["Параметр"]
        if col not in value_columns:
            value_columns.append(col)

    columns=["Дата и время"]+value_columns+["Источник","Лимит"]
    table_df=pd.DataFrame(table_rows)

    for col in columns:
        if col not in table_df.columns:
            table_df[col]=""

    table_df=table_df[columns]
    return sensor_df,table_df


def save_readings_report_to_excel(user_id,days,filename):
    conn=get_connection()
    cur=conn.cursor()

    try:
        if user_id is None:
            cur.execute("""
                SELECT
                    sr.reading_id,
                    sr.telegram_message_id,
                    u.full_name,
                    s.station_name,
                    ss.sensor_model,
                    st.type_name,
                    st.category,
                    st.unit,
                    sr.value,
                    sr.recorded_at,
                    sr.source_type,
                    sr.is_limit_alert
                FROM SensorReadings sr
                JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
                JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
                JOIN Stations s ON ss.station_id=s.station_id
                JOIN Users u ON s.user_id=u.user_id
                WHERE sr.recorded_at >= NOW() - (%s || ' days')::INTERVAL
                ORDER BY sr.recorded_at DESC, sr.reading_id DESC
            """,(days,))
            rows=cur.fetchall()

            if not rows:
                return None

            data=[]
            for r in rows:
                data.append([
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    source_label_db(r[10]),
                    "превышен" if r[11] else "норма"
                ])

            df=pd.DataFrame(data,columns=[
                "ID записи",
                "ID сообщения Telegram",
                "Пользователь",
                "Станция",
                "Модель датчика",
                "Тип",
                "Категория",
                "Ед. изм.",
                "Значение",
                "Время",
                "Источник",
                "Лимит"
            ])
            df.to_excel(filename,index=False)
        else:
            cur.execute("""
                SELECT
                    s.station_name,
                    ss.sensor_model,
                    st.type_name,
                    st.category,
                    st.unit,
                    sr.value,
                    sr.recorded_at,
                    sr.source_type,
                    sr.is_limit_alert,
                    sr.telegram_message_id
                FROM SensorReadings sr
                JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
                JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
                JOIN Stations s ON ss.station_id=s.station_id
                WHERE s.user_id=%s
                  AND sr.recorded_at >= NOW() - (%s || ' days')::INTERVAL
                ORDER BY sr.recorded_at DESC, sr.reading_id DESC
            """,(user_id,days))
            rows=cur.fetchall()

            if not rows:
                return None

            sensor_df,table_df=build_user_wide_report(rows)

            with pd.ExcelWriter(filename,engine="openpyxl") as writer:
                sensor_df.to_excel(writer,index=False,sheet_name="Датчики")
                table_df.to_excel(writer,index=False,sheet_name="Показания")

        autofit_excel_columns(filename)
        return filename

    finally:
        cur.close()
        conn.close()

def save_sensor_reading(station_serial,category,value,source_type="auto",telegram_message_id=None,recorded_at=None):
    ensure_sensor_readings_metadata()
    conn=get_connection()
    cur=conn.cursor()
    try:
        cur.execute("""
            SELECT ss.station_sensor_id,ss.min_value,ss.max_value,s.user_id,s.station_id,s.station_name,u.telegram_id
            FROM Stations s
            JOIN Users u ON s.user_id=u.user_id
            JOIN StationSensors ss ON s.station_id=ss.station_id
            JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
            WHERE s.serial_number=%s AND st.category=%s AND ss.is_active=1
            ORDER BY ss.station_sensor_id
            LIMIT 1
        """,(station_serial,category))
        row=cur.fetchone()
        if not row:
            conn.rollback()
            return False,"Станция или датчик не найдены"
        station_sensor_id,min_value,max_value,user_id,station_id,station_name,telegram_id=row
        alert_message=None
        alert_type=None
        is_limit_alert=False
        if min_value is not None and float(value)<float(min_value):
            alert_type="low"
            alert_message=f"Показатель {category} ниже нормы: {value} < {min_value}"
            is_limit_alert=True
        if max_value is not None and float(value)>float(max_value):
            alert_type="high"
            alert_message=f"Показатель {category} выше нормы: {value} > {max_value}"
            is_limit_alert=True
        if recorded_at is None:
            cur.execute("""
                INSERT INTO SensorReadings (station_sensor_id,value,recorded_at,source_type,telegram_message_id,is_limit_alert)
                VALUES (%s,%s,CURRENT_TIMESTAMP,%s,%s,%s)
            """,(station_sensor_id,value,source_type,telegram_message_id,is_limit_alert))
        else:
            cur.execute("""
                INSERT INTO SensorReadings (station_sensor_id,value,recorded_at,source_type,telegram_message_id,is_limit_alert)
                VALUES (%s,%s,%s,%s,%s,%s)
            """,(station_sensor_id,value,recorded_at,source_type,telegram_message_id,is_limit_alert))
        cur.execute("UPDATE Stations SET last_seen=CURRENT_TIMESTAMP WHERE station_id=%s",(station_id,))
        if alert_message:
            cur.execute("""
                INSERT INTO Alerts (user_id,station_sensor_id,alert_type,message,created_at,is_read)
                VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP,FALSE)
            """,(user_id,station_sensor_id,alert_type,alert_message))
        conn.commit()
        meta={"user_id":user_id,"telegram_id":telegram_id,"station_id":station_id,"station_name":station_name,"alert":alert_message,"is_limit_alert":is_limit_alert}
        return True,meta
    except Exception as e:
        conn.rollback()
        return False,f"Ошибка сохранения показания: {e}"
    finally:
        cur.close()
        conn.close()

def get_users_with_age():
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT user_id,full_name,telegram_id,registered_at,EXTRACT(YEAR FROM age(registered_at)) AS years_registered
        FROM Users
        ORDER BY registered_at
    """)
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def search_stations_by_location(location):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT station_id,station_name,serial_number,locations
        FROM Stations
        WHERE locations ILIKE %s
        ORDER BY station_id
    """,(f"%{location}%",))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def get_today_count(user_id):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("SELECT COUNT(*) FROM UserInteraction WHERE user_id=%s AND DATE(timestamp)=CURRENT_DATE",(user_id,))
    count=cur.fetchone()[0]
    cur.close()
    conn.close()
    return count
def get_user_interactions_report(user_id,days=7):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT u.full_name,s.station_name,it.type_name,ui.value,ui.timestamp,ui.status
        FROM UserInteraction ui
        JOIN Users u ON ui.user_id=u.user_id
        JOIN Stations s ON ui.station_id=s.station_id
        JOIN InteractionTypes it ON ui.interaction_type_id=it.type_id
        WHERE ui.user_id=%s AND ui.timestamp>=NOW()-(%s || ' days')::INTERVAL
        ORDER BY ui.timestamp DESC
        LIMIT 50
    """,(user_id,days))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows
def save_weekly_stats_to_excel(user_id,start_date,end_date,username):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT ui.interaction_id,s.station_name,it.type_name,ui.value,ui.timestamp,ui.status
        FROM UserInteraction ui
        JOIN Stations s ON ui.station_id=s.station_id
        JOIN InteractionTypes it ON ui.interaction_type_id=it.type_id
        WHERE ui.user_id=%s AND DATE(ui.timestamp) BETWEEN %s AND %s
        ORDER BY ui.timestamp DESC
    """,(user_id,start_date,end_date))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return None
    df=pd.DataFrame(rows,columns=["ID","Станция","Тип","Значение","Время","Статус"])
    filename=f"stats_{username}_{start_date}_{end_date}.xlsx"
    df.to_excel(filename,index=False)
    autofit_excel_columns(filename)
    return filename


def get_user_sensor_report(user_id,days=7):
    return get_user_interactions_report(user_id,days)


def get_sensor_readings_for_user_station(user_id,station_id,days):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        WHERE s.user_id=%s AND s.station_id=%s AND sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
        ORDER BY sr.recorded_at DESC
    """,(user_id,station_id,days))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_sensor_readings_for_admin_station(station_id,days):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT u.full_name,s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        JOIN Users u ON s.user_id=u.user_id
        WHERE s.station_id=%s AND sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
        ORDER BY sr.recorded_at DESC
    """,(station_id,days))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_sensor_readings_for_user_station_date(user_id,station_id,target_date):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        WHERE s.user_id=%s AND s.station_id=%s AND DATE(sr.recorded_at)=%s
        ORDER BY sr.recorded_at ASC
    """,(user_id,station_id,target_date))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_sensor_readings_for_admin_station_date(station_id,target_date):
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        SELECT u.full_name,s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
        FROM SensorReadings sr
        JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
        JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
        JOIN Stations s ON ss.station_id=s.station_id
        JOIN Users u ON s.user_id=u.user_id
        WHERE s.station_id=%s AND DATE(sr.recorded_at)=%s
        ORDER BY sr.recorded_at ASC
    """,(station_id,target_date))
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return rows


def save_readings_report_to_excel_station(user_id,station_id,days,filename):
    conn=get_connection()
    cur=conn.cursor()
    try:
        if user_id is None:
            cur.execute("""
                SELECT sr.reading_id,sr.telegram_message_id,u.full_name,s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert
                FROM SensorReadings sr
                JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
                JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
                JOIN Stations s ON ss.station_id=s.station_id
                JOIN Users u ON s.user_id=u.user_id
                WHERE s.station_id=%s AND sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
                ORDER BY sr.recorded_at DESC, sr.reading_id DESC
            """,(station_id,days))
            rows=cur.fetchall()
            if not rows:
                return None
            data=[]
            for r in rows:
                data.append([r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9],source_label_db(r[10]),"превышен" if r[11] else "норма"])
            df=pd.DataFrame(data,columns=["ID записи","ID сообщения Telegram","Пользователь","Станция","Модель датчика","Тип","Категория","Ед. изм.","Значение","Время","Источник","Лимит"])
            df.to_excel(filename,index=False)
        else:
            cur.execute("""
                SELECT s.station_name,ss.sensor_model,st.type_name,st.category,st.unit,sr.value,sr.recorded_at,sr.source_type,sr.is_limit_alert,sr.telegram_message_id
                FROM SensorReadings sr
                JOIN StationSensors ss ON sr.station_sensor_id=ss.station_sensor_id
                JOIN SensorTypes st ON ss.sensor_type_id=st.sensor_type_id
                JOIN Stations s ON ss.station_id=s.station_id
                WHERE s.user_id=%s AND s.station_id=%s AND sr.recorded_at>=NOW()-(%s || ' days')::INTERVAL
                ORDER BY sr.recorded_at DESC, sr.reading_id DESC
            """,(user_id,station_id,days))
            rows=cur.fetchall()
            if not rows:
                return None
            sensor_df,table_df=build_user_wide_report(rows)
            if "Станция" in table_df.columns:
                table_df=table_df.drop(columns=["Станция"])
            with pd.ExcelWriter(filename,engine="openpyxl") as writer:
                sensor_df.to_excel(writer,index=False,sheet_name="Датчики")
                table_df.to_excel(writer,index=False,sheet_name="Показания")
        autofit_excel_columns(filename)
        return filename
    finally:
        cur.close()
        conn.close()
