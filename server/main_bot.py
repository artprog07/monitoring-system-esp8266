from telegram import Update,ReplyKeyboardMarkup,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes,ConversationHandler,MessageHandler,filters,ApplicationHandlerStop
from config import BOT_TOKEN,ADMIN_PASS
try:
    from config import GROUP_CHAT_ID,TECH_BOT_USERNAME
except ImportError:
    GROUP_CHAT_ID=None
    TECH_BOT_USERNAME=None
from report_utils import create_sensor_graph,parse_report_date,parse_time_range,CATEGORY_RU
from db import get_users,get_stations,get_sensors_by_station,add_station,delete_station,delete_user,get_user_by_telegram,get_user_by_id,get_user_stations,get_all_users_for_admin,save_weekly_stats_to_excel,get_connection,get_user_sensor_report,update_user_profile,register_user,init_sensor_types,get_sensor_types,add_station_sensor,delete_station_sensor,get_sensor_readings_for_user,get_sensor_readings_for_admin,save_readings_report_to_excel,save_readings_report_to_excel_station,get_sensor_readings_for_user_station,get_sensor_readings_for_admin_station,get_sensor_readings_for_user_station_date,get_sensor_readings_for_admin_station_date,get_sensor_readings_for_user_date,get_sensor_readings_for_admin_date,save_sensor_reading,update_user_username,get_user_by_username,log_user_activity
from datetime import datetime,timedelta,date
import os
import re
ROLE_SELECT,ADMIN_PASSWORD,REGISTER_NAME,REGISTER_PHONE,REGISTER_EMAIL,ADD_STATION_OWNER,ADD_STATION_NAME,ADD_STATION_SERIAL,ADD_STATION_LOCATION,ADD_STATION_STREET,ADD_STATION_HOUSE,DELETE_STATION_ID,DELETE_USER_ID,REPORT_FORMAT,REPORT_STATION,REPORT_PERIOD_TYPE,REPORT_DAYS,REPORT_GRAPH_DATE_INPUT,REPORT_TIME_FILTER,REPORT_TIME_RANGE,REPORT_GRAPH_MODE,REPORT_GRAPH_SENSOR,MANAGE_SENSORS_STATION,MANAGE_SENSORS_ACTION,MANAGE_SENSORS_ADD_TYPE,MANAGE_SENSORS_ADD_NAME,MANAGE_SENSORS_ADD_LIMITS,MANAGE_SENSORS_ADD_MIN,MANAGE_SENSORS_ADD_MAX,MANAGE_SENSORS_DELETE,EDIT_PROFILE,EDIT_NAME,EDIT_PHONE,EDIT_EMAIL=range(34)
DAILY_LIMIT=10
user_role={}

def normalize_module_name(name):
    value=name.strip().upper()
    value=re.sub(r"_\d{3}$","",value)

    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*",value):
        return None

    return value


def generate_next_station_serial(module_name):
    base=normalize_module_name(module_name)

    if not base:
        return None

    conn=get_connection()
    cur=conn.cursor()

    try:
        cur.execute("SELECT serial_number FROM Stations WHERE serial_number ILIKE %s",(base + "_%",))
        rows=cur.fetchall()
    finally:
        cur.close()
        conn.close()

    used=set()

    for row in rows:
        serial=str(row[0]).upper()
        match=re.match(r"^" + re.escape(base) + r"_(\d{3})$",serial)

        if match:
            used.add(int(match.group(1)))

    next_number=1

    while next_number in used:
        next_number+=1

    return f"{base}_{next_number:03d}"


def get_role_keyboard():
    return ReplyKeyboardMarkup([["Пользователь","Администратор"]],resize_keyboard=True,one_time_keyboard=True)
TEXT_INPUT=filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^Главное меню$")

def is_admin(chat_id):
    return user_role.get(str(chat_id))=="admin"

def get_main_keyboard(chat_id):
    if is_admin(chat_id):
        keyboard=[["Просмотр данных","Управление данными"],["Отчеты","Статистика"],["Активность за сутки","Очистить чат"],["Помощь"]]
    else:
        keyboard=[["Просмотр данных","Управление данными"],["Отчеты","Очистить чат"],["Помощь"]]
    return ReplyKeyboardMarkup(keyboard,resize_keyboard=True)

def get_view_keyboard(chat_id):
    if is_admin(chat_id):
        keyboard=[["/users","/stations"],["/station_sensors","/user_age"],["Главное меню"]]
    else:
        keyboard=[["/me","/stations"],["/station_sensors"],["Главное меню"]]
    return ReplyKeyboardMarkup(keyboard,resize_keyboard=True)

def get_manage_keyboard(chat_id):
    if is_admin(chat_id):
        keyboard=[["/add_station","/delete_station"],["/manage_sensors","/delete_user"],["Главное меню"]]
    else:
        keyboard=[["/add_station","/delete_station"],["/manage_sensors"],["Главное меню"]]
    return ReplyKeyboardMarkup(keyboard,resize_keyboard=True)

def get_reports_keyboard():
    return ReplyKeyboardMarkup([["/sensor_report"],["Главное меню"]],resize_keyboard=True)

def valid_phone(phone):
    return re.fullmatch(r"\+375\d{9}",phone.strip()) is not None

def valid_email(email):
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email.strip()) is not None

def valid_station_serial(serial):
    return re.fullmatch(r"[A-Za-z0-9]+(?:[A-Za-z0-9\-]*)?_\d{3}",serial.strip()) is not None

def log_current_user(update,action_type,description=None):
    try:
        chat_id=str(update.effective_chat.id)
        if is_admin(chat_id):
            return
        user=get_user_by_telegram(chat_id)
        if user:
            log_user_activity(user[0],action_type,description)
    except Exception as e:
        print(e)

async def clear_chat(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"clear_chat","Очистка чата")
    chat_id=str(update.effective_chat.id)
    current_msg_id=update.message.message_id
    for i in range(0,100):
        try:
            msg_id=current_msg_id-i
            if msg_id>0:
                await context.bot.delete_message(chat_id=chat_id,message_id=msg_id)
        except Exception:
            pass
    await context.bot.send_message(chat_id=chat_id,text="Чат очищен. Меню восстановлено.",reply_markup=get_main_keyboard(chat_id))

async def cancel_to_main(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    context.user_data.clear()
    if update.callback_query:
        query=update.callback_query
        await query.answer()
        await query.edit_message_text("Действие отменено. Возврат в главное меню.")
        await context.bot.send_message(chat_id=chat_id,text="Главное меню:",reply_markup=get_main_keyboard(chat_id))
    else:
        await update.message.reply_text("Действие отменено. Главное меню:",reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END

async def ignore_non_private_chats(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type!="private":
        raise ApplicationHandlerStop

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    if update.effective_user and update.effective_user.username:
        update_user_username(chat_id,update.effective_user.username)
    context.user_data.clear()
    await update.message.reply_text("Выберите роль:",reply_markup=get_role_keyboard())
    return ROLE_SELECT

async def role_select_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    text=update.message.text
    if text=="Администратор":
        context.user_data["awaiting_admin_pass"]=True
        context.user_data["skip_menu_once"]=True
        await update.message.reply_text("Введите пароль администратора:")
        return ADMIN_PASSWORD
    if text=="Пользователь":
        user=get_user_by_telegram(chat_id)
        if user:
            user_role[chat_id]="user"
            context.user_data["skip_menu_once"]=True
            log_user_activity(user[0],"login_user","Вход как пользователь")
            await update.message.reply_text("Вы вошли как пользователь.",reply_markup=get_main_keyboard(chat_id))
            return ConversationHandler.END
        context.user_data["skip_menu_once"]=True
        await update.message.reply_text("Вы не зарегистрированы. Введите ваше имя:")
        return REGISTER_NAME
    await update.message.reply_text("Выберите роль кнопкой ниже.")
    return ROLE_SELECT

async def admin_password_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    if update.message.text==ADMIN_PASS:
        user_role[chat_id]="admin"
        context.user_data["skip_menu_once"]=True
        await update.message.reply_text("Вы вошли как администратор.",reply_markup=get_main_keyboard(chat_id))
        return ConversationHandler.END
    context.user_data["skip_menu_once"]=True
    await update.message.reply_text("Неверный пароль. Попробуйте ещё раз:")
    return ADMIN_PASSWORD

async def register_name(update:Update,context:ContextTypes.DEFAULT_TYPE):
    name=update.message.text.strip()
    if len(name)<2:
        await update.message.reply_text("Имя слишком короткое. Введите имя ещё раз:")
        return REGISTER_NAME
    context.user_data["reg_name"]=name
    await update.message.reply_text("Введите номер телефона в формате +375XXXXXXXXX:")
    return REGISTER_PHONE

async def register_phone(update:Update,context:ContextTypes.DEFAULT_TYPE):
    phone=update.message.text.strip()
    if not valid_phone(phone):
        await update.message.reply_text("Неверный формат телефона. Пример: +375291234567")
        return REGISTER_PHONE
    context.user_data["reg_phone"]=phone
    await update.message.reply_text("Введите email:")
    return REGISTER_EMAIL

async def register_email(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    email=update.message.text.strip()
    if not valid_email(email):
        await update.message.reply_text("Неверный формат email. Пример: user@mail.com")
        return REGISTER_EMAIL
    username=update.effective_user.username if update.effective_user else None
    user_id,msg=register_user(chat_id,context.user_data["reg_name"],context.user_data["reg_phone"],email,username)
    if not user_id:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    user_role[chat_id]="user"
    log_user_activity(user_id,"register","Регистрация пользователя")
    await update.message.reply_text("Регистрация завершена. Вы вошли как пользователь.",reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END

async def role_button_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    text=update.message.text
    if text=="Администратор":
        await update.message.reply_text("Введите пароль администратора:")
        context.user_data["manual_admin_login"]=True
        return
    if text=="Пользователь":
        user=get_user_by_telegram(chat_id)
        if user:
            user_role[chat_id]="user"
            await update.message.reply_text("Вы вошли как пользователь.",reply_markup=get_main_keyboard(chat_id))
        else:
            await update.message.reply_text("Вы не зарегистрированы. Введите ваше имя:")
            return REGISTER_NAME

async def manual_admin_password_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    if not context.user_data.get("manual_admin_login"):
        return
    if update.message.text==ADMIN_PASS:
        user_role[chat_id]="admin"
        context.user_data.pop("manual_admin_login",None)
        await update.message.reply_text("Вы вошли как администратор.",reply_markup=get_main_keyboard(chat_id))
    else:
        await update.message.reply_text("Неверный пароль. Попробуйте ещё раз:")

async def handle_menu(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    text=update.message.text
    if context.user_data.pop("skip_menu_once",False):
        return
    if text=="Главное меню":
        context.user_data.clear()
    if context.user_data.get("manual_admin_login"):
        if text==ADMIN_PASS:
            user_role[chat_id]="admin"
            context.user_data.pop("manual_admin_login",None)
            await update.message.reply_text("Вы вошли как администратор.",reply_markup=get_main_keyboard(chat_id))
        else:
            await update.message.reply_text("Неверный пароль. Попробуйте ещё раз:")
        return
    if text=="Администратор":
        context.user_data["manual_admin_login"]=True
        await update.message.reply_text("Введите пароль администратора:")
        return
    if text=="Пользователь":
        user=get_user_by_telegram(chat_id)
        if user:
            user_role[chat_id]="user"
            log_user_activity(user[0],"login_user","Вход как пользователь")
            await update.message.reply_text("Вы вошли как пользователь.",reply_markup=get_main_keyboard(chat_id))
        else:
            await update.message.reply_text("Вы не зарегистрированы. Введите ваше имя:")
            return REGISTER_NAME
        return
    if chat_id not in user_role:
        await update.message.reply_text("Выберите роль:",reply_markup=get_role_keyboard())
        return
    if text=="Просмотр данных":
        await update.message.reply_text("Просмотр данных:",reply_markup=get_view_keyboard(chat_id))
    elif text=="Управление данными":
        await update.message.reply_text("Управление данными:",reply_markup=get_manage_keyboard(chat_id))
    elif text=="Отчеты":
        await update.message.reply_text("Отчеты:",reply_markup=get_reports_keyboard())
    elif text=="Помощь":
        await help_command(update,context)
    elif text=="Главное меню":
        await update.message.reply_text("Главное меню:",reply_markup=get_main_keyboard(chat_id))
    elif text=="Очистить чат":
        await clear_chat(update,context)
    elif text=="Активность за сутки" and is_admin(chat_id):
        await daily_activity(update,context)
    elif text=="Статистика" and is_admin(chat_id):
        await update.message.reply_text("Для статистики используйте /stats @username")

async def help_command(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)

    if is_admin(chat_id):
        text=(
            "Команды администратора:\n"
            "/start - выбор режима работы\n"
            "/users - список пользователей\n"
            "/stations - список станций\n"
            "/daily_activity - активность пользователей за сутки\n"
            "/stats @username - Excel-отчет по активности пользователя\n"
            "/sensor_report - отчет по показаниям датчиков\n"
            "/clear - очистить сообщения бота\n"
            "/help - справка"
        )
    else:
        text=(
            "Команды пользователя:\n"
            "/start - открыть меню\n"
            "/me - мой профиль\n"
            "/my_stations - мои станции\n"
            "/add_station - добавить станцию\n"
            "/manage_sensors - управление датчиками\n"
            "/sensor_report - отчет по показаниям датчиков\n"
            "/clear - очистить сообщения бота\n"
            "/help - справка"
        )

    await update.message.reply_text(text)

async def users(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("Только для администратора.")
        return
    users_list=get_all_users_for_admin()
    if not users_list:
        await update.message.reply_text("Пользователи не найдены.")
        return
    msg="Список пользователей:\n\n"
    for u in users_list:
        reg=u[5].strftime("%d.%m.%Y %H:%M") if u[5] else "нет"
        msg+=f"ID: {u[0]}\nИмя: {u[1]}\nTelegram ID: {u[2]}\nТелефон: {u[3] or 'не указан'}\nEmail: {u[4] or 'не указан'}\nРегистрация: {reg}\n\n"
    await update.message.reply_text(msg[:4000])

async def user_age(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("Только для администратора.")
        return
    users_list=get_all_users_for_admin()
    if not users_list:
        await update.message.reply_text("Пользователи не найдены.")
        return
    msg="Возраст регистрации пользователей:\n\n"
    now=datetime.now()
    for u in users_list:
        if u[5]:
            days=(now-u[5].replace(tzinfo=None)).days
            msg+=f"{u[1]}: {days} дн.\n"
    await update.message.reply_text(msg)

async def stations(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"view_stations","Просмотр станций")
    chat_id=str(update.effective_chat.id)
    if is_admin(chat_id):
        stations_list=get_stations()
    else:
        user=get_user_by_telegram(chat_id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
            return
        stations_list=get_user_stations(user[0])
    if not stations_list:
        await update.message.reply_text("Станции не найдены.")
        return
    msg="Список станций:\n\n"
    for s in stations_list:
        if is_admin(chat_id):
            msg+=f"ID: {s[0]}\nНазвание: {s[1]}\nСерийный: {s[2]}\nЛокация: {s[3]}\nВладелец: {s[4]}\n\n"
        else:
            msg+=f"ID: {s[0]}\nНазвание: {s[1]}\nСерийный: {s[2]}\nЛокация: {s[3]}\n\n"
    await update.message.reply_text(msg[:4000])

async def station_sensors(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"view_station_sensors","Просмотр датчиков станции")
    chat_id=str(update.effective_chat.id)
    if is_admin(chat_id):
        stations_list=get_stations()
    else:
        user=get_user_by_telegram(chat_id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь.")
            return
        stations_list=get_user_stations(user[0])
    if not stations_list:
        await update.message.reply_text("Станций нет.")
        return
    keyboard=[[InlineKeyboardButton(s[1],callback_data=f"ss_{s[0]}")] for s in stations_list]
    await update.message.reply_text("Выберите станцию:",reply_markup=InlineKeyboardMarkup(keyboard))

async def station_sensors_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    station_id=int(query.data.split("_")[1])
    sensors=get_sensors_by_station(station_id)
    if not sensors:
        await query.edit_message_text("На станции нет датчиков.")
        return
    category_ru={"temperature":"Температура","humidity":"Влажность","pressure":"Давление","light":"Освещённость","co2":"CO2"}
    msg="Датчики станции:\n\n"
    for s in sensors:
        min_v=s[4] if s[4] is not None else "не задан"
        max_v=s[5] if s[5] is not None else "не задан"
        active="активен" if s[6] else "неактивен"
        msg+=f"ID: {s[0]}\nМодель: {s[1]}\nКатегория: {category_ru.get(s[2],s[2])}\nЕдиницы: {s[3]}\nМин.: {min_v}\nМакс.: {max_v}\nСтатус: {active}\n\n"
    await query.edit_message_text(msg[:4000])

async def me_command(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"view_profile","Просмотр профиля")
    chat_id=str(update.effective_chat.id)
    if is_admin(chat_id):
        await update.message.reply_text("Вы вошли как администратор. У администратора нет отдельного профиля. Используйте /users.")
        return
    user=get_user_by_telegram(chat_id)
    if not user:
        await update.message.reply_text("Вы не зарегистрированы. Используйте /start.")
        return
    keyboard=[[InlineKeyboardButton("Редактировать профиль",callback_data="edit_profile")]]
    tg_username=update.effective_user.username or "нет"
    reg=user[5].strftime("%d.%m.%Y %H:%M") if user[5] else "нет"
    text=f"Ваш профиль:\n\nИмя: {user[1]}\nTelegram: @{tg_username}\nТелефон: {user[3] or 'не указан'}\nEmail: {user[4] or 'не указан'}\nДата регистрации: {reg}"
    await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup(keyboard))

async def edit_profile_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    keyboard=[[InlineKeyboardButton("Изменить имя",callback_data="edit_name")],[InlineKeyboardButton("Изменить телефон",callback_data="edit_phone")],[InlineKeyboardButton("Изменить email",callback_data="edit_email")]]
    await query.edit_message_text("Что хотите изменить?",reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_PROFILE

async def edit_name_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    await query.edit_message_text("Введите новое имя:")
    return EDIT_NAME

async def save_new_name(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    new_name=update.message.text.strip()
    if len(new_name)<2:
        await update.message.reply_text("Имя слишком короткое. Введите новое имя:")
        return EDIT_NAME
    ok,msg=update_user_profile(chat_id,"full_name",new_name)
    if ok:
        log_current_user(update,"edit_profile","Изменено имя")
    await update.message.reply_text(msg,reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END

async def edit_phone_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    await query.edit_message_text("Введите новый телефон в формате +375XXXXXXXXX:")
    return EDIT_PHONE

async def save_new_phone(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    new_phone=update.message.text.strip()
    if not valid_phone(new_phone):
        await update.message.reply_text("Неверный формат телефона. Пример: +375291234567")
        return EDIT_PHONE
    ok,msg=update_user_profile(chat_id,"phone_number",new_phone)
    if ok:
        log_current_user(update,"edit_profile","Изменён телефон")
    await update.message.reply_text(msg,reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END

async def edit_email_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    await query.edit_message_text("Введите новый email:")
    return EDIT_EMAIL

async def save_new_email(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)
    new_email=update.message.text.strip()
    if not valid_email(new_email):
        await update.message.reply_text("Неверный формат email. Пример: user@mail.com")
        return EDIT_EMAIL
    ok,msg=update_user_profile(chat_id,"email",new_email)
    if ok:
        log_current_user(update,"edit_profile","Изменён email")
    await update.message.reply_text(msg,reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END

async def add_station_start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"start_add_station","Начало добавления станции")
    chat_id=str(update.effective_chat.id)
    context.user_data.clear()
    if is_admin(chat_id):
        users_list=get_all_users_for_admin()
        if not users_list:
            await update.message.reply_text("Нет пользователей, которым можно добавить станцию.")
            return ConversationHandler.END
        keyboard=[[InlineKeyboardButton(f"{u[1]} (ID: {u[0]})",callback_data=f"asuser_{u[0]}")] for u in users_list]
        await update.message.reply_text("Выберите владельца станции:",reply_markup=InlineKeyboardMarkup(keyboard))
        return ADD_STATION_OWNER
    user=get_user_by_telegram(chat_id)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
        return ConversationHandler.END
    context.user_data["station_owner_id"]=user[0]
    await update.message.reply_text("Введите название станции:")
    return ADD_STATION_NAME

async def add_station_owner_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    user_id=int(query.data.split("_")[1])
    context.user_data["station_owner_id"]=user_id
    await query.edit_message_text("Введите название станции:")
    return ADD_STATION_NAME

async def add_station_name(update:Update,context:ContextTypes.DEFAULT_TYPE):
    name=update.message.text.strip()

    if not name:
        await update.message.reply_text("Введите название станции.")
        return ADD_STATION_NAME

    context.user_data["station_name"]=name
    await update.message.reply_text("Введите название главного модуля станции. Например: ESP8266")
    return ADD_STATION_SERIAL



async def add_station_serial(update:Update,context:ContextTypes.DEFAULT_TYPE):
    module_name=update.message.text.strip()
    serial=generate_next_station_serial(module_name)

    if not serial:
        await update.message.reply_text(
            "Название главного модуля должно содержать только латинские буквы, цифры, _ или -.\n"
            "Пример: ESP8266"
        )
        return ADD_STATION_SERIAL

    context.user_data["station_module_name"]=normalize_module_name(module_name)
    context.user_data["station_serial"]=serial

    await update.message.reply_text(
        f"Ваш серийный номер станции: {serial}\n\n"
        "Введите локацию станции. Например: квартира, балкон, кабинет, теплица:"
    )
    return ADD_STATION_LOCATION



async def add_station_location(update:Update,context:ContextTypes.DEFAULT_TYPE):
    location=update.message.text.strip()

    if not location:
        await update.message.reply_text("Введите локацию станции.")
        return ADD_STATION_LOCATION

    chat_id=str(update.effective_chat.id)

    if is_admin(chat_id):
        user_id=context.user_data.get("add_station_user_id")

        if not user_id:
            await update.message.reply_text("Ошибка выбора пользователя.")
            return ConversationHandler.END
    else:
        user=get_user_by_telegram(chat_id)

        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь.")
            return ConversationHandler.END

        user_id=user[0]

    result=add_station(
        context.user_data["station_name"],
        context.user_data["station_serial"],
        location,
        user_id
    )

    if isinstance(result,(list,tuple)):
        ok=result[0]
        message=result[1] if len(result)>1 else "Операция выполнена."
    else:
        ok=True
        message=str(result)

    if ok:
        log_current_user(update,"add_station",f"Добавлена станция {context.user_data['station_serial']}")

    context.user_data.pop("in_add_station",None)

    await update.message.reply_text(message,reply_markup=get_main_keyboard(chat_id))
    return ConversationHandler.END



async def delete_station_start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"start_delete_station","Начало удаления станции")
    chat_id=str(update.effective_chat.id)
    if is_admin(chat_id):
        stations_list=get_stations()
    else:
        user=get_user_by_telegram(chat_id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь.")
            return ConversationHandler.END
        stations_list=get_user_stations(user[0])
    if not stations_list:
        await update.message.reply_text("Нет станций.")
        return ConversationHandler.END
    keyboard=[[InlineKeyboardButton(f"{s[1]} ({s[2]})",callback_data=f"delstation_{s[0]}")] for s in stations_list]
    await update.message.reply_text("Выберите станцию для удаления:",reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_STATION_ID

async def delete_station_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    station_id=int(query.data.split("_")[1])
    result=delete_station(station_id)
    await query.edit_message_text(result)
    return ConversationHandler.END

async def delete_user_start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("Только для администратора.")
        return ConversationHandler.END
    users_list=get_all_users_for_admin()
    if not users_list:
        await update.message.reply_text("Нет пользователей.")
        return ConversationHandler.END
    keyboard=[[InlineKeyboardButton(f"{u[1]} (ID: {u[0]})",callback_data=f"deluser_{u[0]}")] for u in users_list]
    await update.message.reply_text("Выберите пользователя:",reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_USER_ID

async def delete_user_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    user_id=int(query.data.split("_")[1])
    result=delete_user(user_id)
    await query.edit_message_text(result)
    return ConversationHandler.END

async def ask_report_station(update,context):
    chat_id=str(update.effective_chat.id)
    user_id=context.user_data.get("report_user_id")

    if user_id is None:
        stations=get_stations()
    else:
        stations=get_user_stations(user_id)

    if not stations:
        await update.message.reply_text("Нет доступных метеостанций для формирования отчета.")
        return ConversationHandler.END

    keyboard=[]

    for station in stations:
        station_id=station[0]
        station_name=station[1]
        serial=station[2] if len(station)>2 else ""
        keyboard.append([InlineKeyboardButton(f"{station_name} ({serial})",callback_data=f"report_station_{station_id}")])

    await update.message.reply_text("Выберите метеостанцию для отчета:",reply_markup=InlineKeyboardMarkup(keyboard))
    return REPORT_STATION


async def report_station_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    station_id=int(query.data.replace("report_station_",""))
    context.user_data["report_station_id"]=station_id

    keyboard=[
        [InlineKeyboardButton("Excel файл",callback_data="report_excel")],
        [InlineKeyboardButton("График",callback_data="report_graph")]
    ]

    await query.edit_message_text("Выберите формат отчета:",reply_markup=InlineKeyboardMarkup(keyboard))
    return REPORT_FORMAT


async def sensor_report(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat_id=str(update.effective_chat.id)

    context.user_data.pop("report_station_id",None)
    context.user_data.pop("specific_date",None)
    context.user_data.pop("time_start",None)
    context.user_data.pop("time_end",None)

    if is_admin(chat_id):
        context.user_data["report_user_id"]=None
    else:
        user=get_user_by_telegram(chat_id)

        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь.")
            return ConversationHandler.END

        context.user_data["report_user_id"]=user[0]

    return await ask_report_station(update,context)



async def report_format_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    fmt=query.data.split("_")[1]
    context.user_data["report_format"]=fmt
    keyboard=[
        [InlineKeyboardButton("За период в днях",callback_data="period_days")],
        [InlineKeyboardButton("За конкретную дату",callback_data="period_exact")]
    ]
    await query.edit_message_text("Выберите период отчета:",reply_markup=InlineKeyboardMarkup(keyboard))
    return REPORT_PERIOD_TYPE

async def report_period_type_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=="period_days":
        await query.edit_message_text("Введите длительность периода в днях от 1 до 30:")
        return REPORT_DAYS
    await query.edit_message_text("Введите дату в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.\nНапример: 14.05.2026")
    return REPORT_GRAPH_DATE_INPUT

async def report_days_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        days=int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 30.")
        return REPORT_DAYS
    if days<1:
        days=1
    if days>30:
        days=30
    context.user_data["report_days"]=days
    context.user_data["specific_date"]=None
    fmt=context.user_data.get("report_format")
    if fmt=="graph":
        await ask_graph_mode_message(update)
        return REPORT_GRAPH_MODE
    await send_non_graph_report(update,context)
    return ConversationHandler.END

async def report_date_input_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        target_date=parse_report_date(update.message.text)
    except Exception:
        await update.message.reply_text("Неверный формат даты. Пример: 14.05.2026 или 2026-05-14")
        return REPORT_GRAPH_DATE_INPUT
    context.user_data["specific_date"]=target_date
    context.user_data["report_days"]=1
    fmt=context.user_data.get("report_format")
    if fmt=="graph":
        keyboard=[
            [InlineKeyboardButton("Да, выбрать часы",callback_data="time_yes")],
            [InlineKeyboardButton("Нет, весь день",callback_data="time_no")]
        ]
        await update.message.reply_text("Выбран один день. Нужен конкретный промежуток времени?",reply_markup=InlineKeyboardMarkup(keyboard))
        return REPORT_TIME_FILTER
    await send_non_graph_report(update,context)
    return ConversationHandler.END

def source_label(source):
    labels={
        "auto":"автоматическая отправка",
        "manual_lcd":"ручная отправка с меню станции",
        "manual_web":"ручная отправка с веб-интерфейса",
        None:"старые данные",
        "None":"старые данные",
        "":"старые данные"
    }
    return labels.get(source,str(source))


def format_text_report_rows(rows,user_id,title):
    msg=f"Показания {title}:\n\n"

    for r in rows:
        if user_id is None:
            source=source_label(r[8] if len(r)>8 else None)
            limit_text="да" if len(r)>9 and r[9] else "нет"
            msg+=(
                f"Пользователь: {r[0]}\n"
                f"Станция: {r[1]}\n"
                f"Датчик: {r[2]}\n"
                f"Тип: {r[3]}\n"
                f"Значение: {r[6]} {r[5]}\n"
                f"Время: {r[7]}\n"
                f"Источник: {source}\n"
                f"Выход за лимит: {limit_text}\n\n"
            )
        else:
            source=source_label(r[7] if len(r)>7 else None)
            limit_text="да" if len(r)>8 and r[8] else "нет"
            msg+=(
                f"Станция: {r[0]}\n"
                f"Датчик: {r[1]}\n"
                f"Тип: {r[2]}\n"
                f"Значение: {r[5]} {r[4]}\n"
                f"Время: {r[6]}\n"
                f"Источник: {source}\n"
                f"Выход за лимит: {limit_text}\n\n"
            )

    return msg


async def send_text_or_file(update,text,filename_prefix="sensor_report"):
    if len(text)<=3800:
        await update.message.reply_text(text)
        return

    filename=f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filename,"w",encoding="utf-8") as f:
        f.write(text)

    await update.message.reply_text("Отчет получился слишком большим для одного сообщения. Отправляю полный отчет файлом.")
    with open(filename,"rb") as f:
        await update.message.reply_document(document=f,filename=filename)

    os.remove(filename)


def readings_rows_to_dataframe(rows,user_id):
    import pandas as pd

    if user_id is None:
        data=[]
        for r in rows:
            data.append([
                r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],
                source_label(r[8] if len(r)>8 else None),
                "превышен" if len(r)>9 and r[9] else "норма"
            ])
        return pd.DataFrame(data,columns=["Пользователь","Станция","Модель датчика","Тип","Категория","Ед. изм.","Значение","Время","Источник","Лимит"])

    data=[]
    for r in rows:
        data.append([
            r[1],r[2],r[3],r[4],r[5],r[6],
            source_label(r[7] if len(r)>7 else None),
            "превышен" if len(r)>8 and r[8] else "норма"
        ])
    return pd.DataFrame(data,columns=["Модель датчика","Тип","Категория","Ед. изм.","Значение","Время","Источник","Лимит"])



async def send_non_graph_report(update,context):
    user_id=context.user_data.get("report_user_id")
    station_id=context.user_data.get("report_station_id")
    fmt=context.user_data.get("report_format")
    days=context.user_data.get("report_days",7)
    specific_date=context.user_data.get("specific_date")

    if fmt=="excel":
        filename=f"readings_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        if specific_date:
            rows=get_sensor_readings_for_admin_station_date(station_id,specific_date) if user_id is None else get_sensor_readings_for_user_station_date(user_id,station_id,specific_date)

            if not rows:
                await update.message.reply_text("Нет показаний за выбранный период.")
                return

            df=readings_rows_to_dataframe(rows,user_id)
            df.to_excel(filename,index=False)
            file_path=filename
        else:
            file_path=save_readings_report_to_excel_station(user_id,station_id,days,filename)

        if not file_path:
            await update.message.reply_text("Нет показаний за выбранный период.")
            return

        with open(file_path,"rb") as f:
            await update.message.reply_document(document=f,filename=filename)

        os.remove(file_path)
        return

    if specific_date:
        rows=get_sensor_readings_for_admin_station_date(station_id,specific_date) if user_id is None else get_sensor_readings_for_user_station_date(user_id,station_id,specific_date)
        title=f"за {specific_date.strftime('%d.%m.%Y')}"
    else:
        rows=get_sensor_readings_for_admin_station(station_id,days) if user_id is None else get_sensor_readings_for_user_station(user_id,station_id,days)
        title=f"за последние {days} дн."

    if not rows:
        await update.message.reply_text("Нет показаний за выбранный период.")
        return

    msg=format_text_report_rows(rows,user_id,title)
    await send_text_or_file(update,msg)

async def report_time_filter_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=="time_yes":
        await query.edit_message_text("Введите промежуток времени в формате ЧЧ-ЧЧ или ЧЧ:ММ-ЧЧ:ММ.\nНапример: 08-14 или 08:30-13:40")
        return REPORT_TIME_RANGE
    context.user_data["time_start"]=None
    context.user_data["time_end"]=None
    await ask_graph_mode(query)
    return REPORT_GRAPH_MODE

async def report_time_range_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        start,end=parse_time_range(update.message.text)
    except Exception:
        await update.message.reply_text("Неверный формат. Пример: 08-14 или 08:30-13:40")
        return REPORT_TIME_RANGE
    context.user_data["time_start"]=start
    context.user_data["time_end"]=end
    await ask_graph_mode_message(update)
    return REPORT_GRAPH_MODE

async def ask_graph_mode(query):
    keyboard=[
        [InlineKeyboardButton("Все параметры по отдельности",callback_data="graphmode_separate")],
        [InlineKeyboardButton("Выбрать один параметр",callback_data="graphmode_single")]
    ]
    await query.edit_message_text("Какой график построить?",reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_graph_mode_message(update):
    keyboard=[
        [InlineKeyboardButton("Все параметры по отдельности",callback_data="graphmode_separate")],
        [InlineKeyboardButton("Выбрать один параметр",callback_data="graphmode_single")]
    ]
    await update.message.reply_text("Какой график построить?",reply_markup=InlineKeyboardMarkup(keyboard))

async def report_graph_mode_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    mode=query.data.replace("graphmode_","")
    context.user_data["graph_mode"]=mode
    if mode=="separate":
        await send_graph_report(query,context,"separate",None)
        return ConversationHandler.END
    user_id=context.user_data.get("report_user_id")
    station_id=context.user_data.get("report_station_id")
    days=context.user_data.get("report_days",7)
    specific_date=context.user_data.get("specific_date")
    rows=get_sensor_readings_for_admin_station_date(station_id,specific_date) if (user_id is None and specific_date) else get_sensor_readings_for_user_station_date(user_id,station_id,specific_date) if specific_date else get_sensor_readings_for_admin_station(station_id,days) if user_id is None else get_sensor_readings_for_user_station(user_id,station_id,days)
    if not rows:
        await query.edit_message_text("Нет показаний за выбранный период.")
        return ConversationHandler.END
    if user_id is None:
        categories=sorted(set(str(r[4]) for r in rows))
    else:
        categories=sorted(set(str(r[3]) for r in rows))
    keyboard=[[InlineKeyboardButton(CATEGORY_RU.get(c,c),callback_data=f"graphsensor_{c}")] for c in categories]
    await query.edit_message_text("Выберите параметр:",reply_markup=InlineKeyboardMarkup(keyboard))
    return REPORT_GRAPH_SENSOR

async def report_graph_sensor_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    category=query.data.replace("graphsensor_","")
    await send_graph_report(query,context,"single",category)
    return ConversationHandler.END

async def send_graph_report(query,context,mode,category):
    user_id=context.user_data.get("report_user_id")
    station_id=context.user_data.get("report_station_id")
    days=context.user_data.get("report_days",7)
    specific_date=context.user_data.get("specific_date")
    time_start=context.user_data.get("time_start")
    time_end=context.user_data.get("time_end")
    if specific_date:
        rows=get_sensor_readings_for_admin_station_date(station_id,specific_date) if user_id is None else get_sensor_readings_for_user_station_date(user_id,station_id,specific_date)
    else:
        rows=get_sensor_readings_for_admin_station(station_id,days) if user_id is None else get_sensor_readings_for_user_station(user_id,station_id,days)
    if not rows:
        await query.edit_message_text("Нет показаний за выбранный период.")
        return
    filename=f"readings_graph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    average_10min=True if specific_date else False
    period_start=None
    period_end=None
    if not specific_date:
        period_end=datetime.now().date()
        period_start=period_end-timedelta(days=days-1)

    file_path,error=create_sensor_graph(
        rows,
        user_id,
        filename,
        mode=mode,
        selected_category=category,
        specific_date=specific_date,
        time_start=time_start,
        time_end=time_end,
        average_10min=average_10min,
        period_start=period_start,
        period_end=period_end
    )
    if error:
        await query.edit_message_text(error)
        return
    await query.edit_message_text("График сформирован.")
    with open(file_path,"rb") as f:
        await context.bot.send_document(chat_id=query.message.chat_id,document=f,filename=filename)
    os.remove(file_path)


async def stats_week(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("Только для администратора.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /stats @username")
        return
    username=context.args[0].strip()
    user=get_user_by_username(username)
    if not user:
        await update.message.reply_text("Пользователь не найден по тегу. Проверьте, что он запускал /start после обновления бота, и что у него есть Telegram username.")
        return
    user_id=user[0]
    clean_username=username[1:] if username.startswith("@") else username
    end_date=datetime.now().date()
    start_date=end_date-timedelta(days=7)
    file_path=save_weekly_stats_to_excel(user_id,start_date,end_date,clean_username)
    if not file_path:
        await update.message.reply_text(f"Нет данных для @{clean_username} за 7 дней.")
        return
    with open(file_path,"rb") as f:
        await update.message.reply_document(f,filename=f"stats_{clean_username}_{start_date}_{end_date}.xlsx")
    os.remove(file_path)

async def daily_activity(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("Только для администратора.")
        return
    conn=get_connection()
    cur=conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS UserActivityLog (
            activity_id SERIAL PRIMARY KEY,
            user_id INT NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
            action_type VARCHAR(100) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.execute("""
        SELECT u.telegram_id,u.full_name,COUNT(ual.activity_id) AS cnt,MAX(ual.created_at) AS last_time
        FROM Users u
        LEFT JOIN UserActivityLog ual ON u.user_id=ual.user_id AND ual.created_at>=NOW()-INTERVAL '24 hours'
        GROUP BY u.user_id,u.telegram_id,u.full_name
        ORDER BY cnt DESC
    """)
    summary_rows=cur.fetchall()
    cur.execute("""
        SELECT u.full_name,u.telegram_id,ual.action_type,ual.description,ual.created_at
        FROM UserActivityLog ual
        JOIN Users u ON u.user_id=ual.user_id
        WHERE ual.created_at>=NOW()-INTERVAL '24 hours'
        ORDER BY ual.created_at DESC
    """)
    detail_rows=cur.fetchall()
    cur.close()
    conn.close()
    if not summary_rows:
        await update.message.reply_text("Нет данных за 24 часа.")
        return
    import pandas as pd
    filename="daily_activity.xlsx"
    summary_df=pd.DataFrame(summary_rows,columns=["Telegram ID","Имя","Количество действий","Последнее действие"])
    details_df=pd.DataFrame(detail_rows,columns=["Имя","Telegram ID","Действие","Описание","Время"])
    with pd.ExcelWriter(filename,engine="openpyxl") as writer:
        summary_df.to_excel(writer,index=False,sheet_name="Итог")
        details_df.to_excel(writer,index=False,sheet_name="Детали")
    with open(filename,"rb") as f:
        await update.message.reply_document(f,filename=filename)
    os.remove(filename)

async def manage_sensors_start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    log_current_user(update,"start_manage_sensors","Начало управления датчиками")
    chat_id=str(update.effective_chat.id)
    context.user_data.clear()
    if is_admin(chat_id):
        stations_list=get_stations()
    else:
        user=get_user_by_telegram(chat_id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь.")
            return ConversationHandler.END
        stations_list=get_user_stations(user[0])
    if not stations_list:
        await update.message.reply_text("У вас нет станций.")
        return ConversationHandler.END
    keyboard=[[InlineKeyboardButton(f"{s[1]} ({s[2]})",callback_data=f"ms_{s[0]}")] for s in stations_list]
    await update.message.reply_text("Выберите станцию:",reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_STATION

async def manage_sensors_station_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    station_id=int(query.data.split("_")[1])
    context.user_data["manage_station_id"]=station_id
    keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
    await query.edit_message_text("Выберите действие:",reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_ACTION

async def manage_sensors_action_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    action=query.data.split("_")[1]
    if action=="add":
        sensor_types=get_sensor_types()
        keyboard=[[InlineKeyboardButton(f"{st[1]} ({st[2]})",callback_data=f"ms_addtype_{st[3]}")] for st in sensor_types]
        keyboard.append([InlineKeyboardButton("Назад",callback_data="ms_back")])
        await query.edit_message_text("Выберите тип датчика:",reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_ADD_TYPE
    if action=="del":
        station_id=context.user_data["manage_station_id"]
        sensors=get_sensors_by_station(station_id)
        if not sensors:
            keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
            await query.edit_message_text("На станции нет датчиков.",reply_markup=InlineKeyboardMarkup(keyboard))
            return MANAGE_SENSORS_ACTION
        keyboard=[[InlineKeyboardButton(f"{s[1]} ({s[2]})",callback_data=f"ms_del_{s[0]}")] for s in sensors]
        keyboard.append([InlineKeyboardButton("Назад",callback_data="ms_back")])
        await query.edit_message_text("Выберите датчик для удаления:",reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_DELETE
    if action=="back":
        chat_id=str(query.message.chat_id)
        if is_admin(chat_id):
            stations_list=get_stations()
        else:
            user=get_user_by_telegram(chat_id)
            if not user:
                await query.edit_message_text("Ошибка регистрации. Используйте /start.")
                return ConversationHandler.END
            stations_list=get_user_stations(user[0])
        if not stations_list:
            await query.edit_message_text("Станций нет.")
            return ConversationHandler.END
        keyboard=[[InlineKeyboardButton(f"{s[1]} ({s[2]})",callback_data=f"ms_{s[0]}")] for s in stations_list]
        await query.edit_message_text("Выберите станцию:",reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_STATION
    return MANAGE_SENSORS_ACTION

async def manage_sensors_add_type_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=="ms_back":
        keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
        await query.edit_message_text("Выберите действие:",reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_ACTION
    category=query.data.replace("ms_addtype_","")
    context.user_data["add_sensor_category"]=category
    await query.edit_message_text("Введите модель датчика:")
    return MANAGE_SENSORS_ADD_NAME

async def manage_sensors_add_name_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    model=update.message.text.strip()
    if len(model)<2:
        await update.message.reply_text("Введите корректную модель датчика:")
        return MANAGE_SENSORS_ADD_NAME
    context.user_data["add_sensor_model"]=model
    keyboard=[[InlineKeyboardButton("Да, включить предупреждения",callback_data="limits_yes")],[InlineKeyboardButton("Нет, не предупреждать",callback_data="limits_no")],[InlineKeyboardButton("Назад",callback_data="limits_back")]]
    await update.message.reply_text("Включить предупреждения по минимальному и максимальному значению?",reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_ADD_LIMITS

async def manage_sensors_limits_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=="limits_back":
        sensor_types=get_sensor_types()
        keyboard=[[InlineKeyboardButton(f"{st[1]} ({st[2]})",callback_data=f"ms_addtype_{st[3]}")] for st in sensor_types]
        keyboard.append([InlineKeyboardButton("Назад",callback_data="ms_back")])
        await query.edit_message_text("Выберите тип датчика:",reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_ADD_TYPE
    if query.data=="limits_no":
        station_id=context.user_data["manage_station_id"]
        category=context.user_data["add_sensor_category"]
        model=context.user_data["add_sensor_model"]
        ok,msg=add_station_sensor(station_id,category,model,None,None)
        keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
        await query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup(keyboard))
        return MANAGE_SENSORS_ACTION
    await query.edit_message_text("Введите минимально допустимое значение:")
    return MANAGE_SENSORS_ADD_MIN

async def manage_sensors_add_min_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        min_value=float(update.message.text.replace(",",".").strip())
    except ValueError:
        await update.message.reply_text("Введите число. Например: 10 или 10.5")
        return MANAGE_SENSORS_ADD_MIN
    context.user_data["add_sensor_min"]=min_value
    await update.message.reply_text("Введите максимально допустимое значение:")
    return MANAGE_SENSORS_ADD_MAX

async def manage_sensors_add_max_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        max_value=float(update.message.text.replace(",",".").strip())
    except ValueError:
        await update.message.reply_text("Введите число. Например: 30 или 30.5")
        return MANAGE_SENSORS_ADD_MAX
    min_value=context.user_data["add_sensor_min"]
    if max_value<=min_value:
        await update.message.reply_text("Максимум должен быть больше минимума. Введите максимум ещё раз:")
        return MANAGE_SENSORS_ADD_MAX
    station_id=context.user_data["manage_station_id"]
    category=context.user_data["add_sensor_category"]
    model=context.user_data["add_sensor_model"]
    ok,msg=add_station_sensor(station_id,category,model,min_value,max_value)
    keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
    await update.message.reply_text(msg,reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_ACTION

async def manage_sensors_delete_back_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
    await query.edit_message_text("Выберите действие:",reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_ACTION

async def manage_sensors_delete_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    sensor_id=int(query.data.split("_")[2])
    result=delete_station_sensor(sensor_id)
    keyboard=[[InlineKeyboardButton("Добавить датчик",callback_data="ms_add")],[InlineKeyboardButton("Удалить датчик",callback_data="ms_del")],[InlineKeyboardButton("Назад",callback_data="ms_back")]]
    await query.edit_message_text(result,reply_markup=InlineKeyboardMarkup(keyboard))
    return MANAGE_SENSORS_ACTION

def parse_esp_message(text):
    if not text:
        return None
    normalized=text.replace(";",",").replace("\n",",")
    parts=[p.strip() for p in normalized.split(",") if p.strip()]
    data={}
    for part in parts:
        if "=" in part:
            key,value=part.split("=",1)
        elif ":" in part:
            key,value=part.split(":",1)
        else:
            continue
        key=key.strip().lower()
        value=value.strip()
        data[key]=value
    station=data.get("station") or data.get("esp") or data.get("serial") or data.get("station_serial")
    if not station:
        for part in parts:
            if part.upper().startswith("ESP"):
                station=part.strip()
                break
    if not station:
        return None
    aliases={"temp":"temperature","t":"temperature","температура":"temperature","hum":"humidity","h":"humidity","влажность":"humidity","press":"pressure","p":"pressure","давление":"pressure","освещенность":"light","освещённость":"light","lux":"light","co2":"co2","co₂":"co2"}
    readings={}
    for key,value in data.items():
        if key in ["station","esp","serial","station_serial"]:
            continue
        category=aliases.get(key,key)
        if category not in ["temperature","humidity","pressure","light","co2"]:
            continue
        try:
            readings[category]=float(value.replace(",","."))
        except ValueError:
            continue
    if not readings:
        return None
    return station,readings

async def esp_cache_message_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if GROUP_CHAT_ID is None:
        return
    if str(update.effective_chat.id)!=str(GROUP_CHAT_ID):
        return
    text=update.effective_message.text or update.effective_message.caption or ""
    parsed=parse_esp_message(text)
    if not parsed:
        return
    station_serial,readings=parsed
    saved=0
    alerts=[]
    for category,value in readings.items():
        ok,msg=save_sensor_reading(station_serial,category,value)
        if ok:
            saved+=1
            if msg:
                alerts.append(msg)
    if alerts:
        for msg in alerts:
            await context.bot.send_message(chat_id=update.effective_chat.id,text=f"⚠️ {station_serial}: {msg}")


def main():
    init_sensor_types()
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(~filters.ChatType.PRIVATE,ignore_non_private_chats),group=-1000)
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("start",start),MessageHandler(filters.Regex("^(Пользователь|Администратор)$"),role_select_handler)],states={ROLE_SELECT:[MessageHandler(filters.Regex("^(Пользователь|Администратор)$"),role_select_handler)],ADMIN_PASSWORD:[MessageHandler(TEXT_INPUT,admin_password_handler)],REGISTER_NAME:[MessageHandler(TEXT_INPUT,register_name)],REGISTER_PHONE:[MessageHandler(TEXT_INPUT,register_phone)],REGISTER_EMAIL:[MessageHandler(TEXT_INPUT,register_email)]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("add_station",add_station_start)],states={ADD_STATION_OWNER:[CallbackQueryHandler(add_station_owner_callback,pattern=r"^asuser_\d+$")],ADD_STATION_NAME:[MessageHandler(TEXT_INPUT,add_station_name)],ADD_STATION_SERIAL:[MessageHandler(TEXT_INPUT,add_station_serial)],ADD_STATION_LOCATION:[MessageHandler(TEXT_INPUT,add_station_location)]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("delete_station",delete_station_start)],states={DELETE_STATION_ID:[CallbackQueryHandler(delete_station_callback,pattern=r"^delstation_\d+$")]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("delete_user",delete_user_start)],states={DELETE_USER_ID:[CallbackQueryHandler(delete_user_callback,pattern=r"^deluser_\d+$")]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("sensor_report",sensor_report)],
        states={
            REPORT_STATION:[CallbackQueryHandler(report_station_callback,pattern=r"^report_station_\d+$")],REPORT_FORMAT:[CallbackQueryHandler(report_format_callback,pattern=r"^report_(excel|graph)$")],
            REPORT_PERIOD_TYPE:[CallbackQueryHandler(report_period_type_callback,pattern=r"^period_(days|exact)$")],
            REPORT_DAYS:[MessageHandler(TEXT_INPUT,report_days_handler)],
            REPORT_GRAPH_DATE_INPUT:[MessageHandler(TEXT_INPUT,report_date_input_handler)],
            REPORT_TIME_FILTER:[CallbackQueryHandler(report_time_filter_callback,pattern=r"^time_(yes|no)$")],
            REPORT_TIME_RANGE:[MessageHandler(TEXT_INPUT,report_time_range_handler)],
            REPORT_GRAPH_MODE:[CallbackQueryHandler(report_graph_mode_callback,pattern=r"^graphmode_(separate|single)$")],
            REPORT_GRAPH_SENSOR:[CallbackQueryHandler(report_graph_sensor_callback,pattern=r"^graphsensor_")]
        },
        fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("manage_sensors",manage_sensors_start)],states={MANAGE_SENSORS_STATION:[CallbackQueryHandler(manage_sensors_station_callback,pattern=r"^ms_\d+$")],MANAGE_SENSORS_ACTION:[CallbackQueryHandler(manage_sensors_action_callback,pattern=r"^ms_(add|del|back)$")],MANAGE_SENSORS_ADD_TYPE:[CallbackQueryHandler(manage_sensors_add_type_callback,pattern=r"^(ms_addtype_|ms_back)")],MANAGE_SENSORS_ADD_NAME:[MessageHandler(TEXT_INPUT,manage_sensors_add_name_callback)],MANAGE_SENSORS_ADD_LIMITS:[CallbackQueryHandler(manage_sensors_limits_callback,pattern=r"^limits_(yes|no|back)$")],MANAGE_SENSORS_ADD_MIN:[MessageHandler(TEXT_INPUT,manage_sensors_add_min_callback)],MANAGE_SENSORS_ADD_MAX:[MessageHandler(TEXT_INPUT,manage_sensors_add_max_callback)],MANAGE_SENSORS_DELETE:[CallbackQueryHandler(manage_sensors_delete_callback,pattern=r"^ms_del_\d+$"),CallbackQueryHandler(manage_sensors_delete_back_callback,pattern=r"^ms_back$")]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(edit_profile_callback,pattern=r"^edit_profile$")],states={EDIT_PROFILE:[CallbackQueryHandler(edit_name_callback,pattern=r"^edit_name$"),CallbackQueryHandler(edit_phone_callback,pattern=r"^edit_phone$"),CallbackQueryHandler(edit_email_callback,pattern=r"^edit_email$")],EDIT_NAME:[MessageHandler(TEXT_INPUT,save_new_name)],EDIT_PHONE:[MessageHandler(TEXT_INPUT,save_new_phone)],EDIT_EMAIL:[MessageHandler(TEXT_INPUT,save_new_email)]},fallbacks=[MessageHandler(filters.Regex("^Главное меню$"),cancel_to_main),CommandHandler("start",start)]))
    app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CommandHandler("users",users))
    app.add_handler(CommandHandler("user_age",user_age))
    app.add_handler(CommandHandler("stations",stations))
    app.add_handler(CommandHandler("station_sensors",station_sensors))
    app.add_handler(CommandHandler("stats",stats_week))
    app.add_handler(CommandHandler("clear",clear_chat))
    app.add_handler(CommandHandler("me",me_command))
    app.add_handler(CallbackQueryHandler(station_sensors_callback,pattern=r"^ss_\d+$"))
    app.add_handler(MessageHandler(filters.Chat(chat_id=int(GROUP_CHAT_ID)) & (filters.TEXT | filters.CaptionRegex(r".*")),esp_cache_message_handler),group=1) if GROUP_CHAT_ID is not None else None
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_menu),group=10)
    print("Бот запущен")
    app.run_polling()
if __name__=="__main__":
    main()
