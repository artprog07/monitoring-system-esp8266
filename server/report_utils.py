from datetime import datetime, timedelta, time
import os

CATEGORY_RU = {
    "temperature": "Температура",
    "humidity": "Влажность",
    "pressure": "Давление",
    "light": "Освещённость",
    "co2": "CO2"
}

CATEGORY_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "hPa",
    "light": "lx",
    "co2": "ppm"
}


def parse_report_date(text):
    value = text.strip()

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    raise ValueError("Неверный формат даты")


def parse_time_range(text):
    value = text.strip().replace(" ", "")

    if "-" not in value:
        raise ValueError("Нет разделителя '-'")

    left, right = value.split("-", 1)

    def parse_one(part):
        if ":" in part:
            h, m = part.split(":", 1)
        else:
            h, m = part, "0"

        h = int(h)
        m = int(m)

        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError("Время вне диапазона")

        return time(h, m)

    start = parse_one(left)
    end = parse_one(right)

    if end <= start:
        raise ValueError("Конец должен быть позже начала")

    return start, end


def normalize_rows(rows, user_id):
    prepared = []

    if user_id is None:
        for r in rows:
            prepared.append({
                "station": str(r[1]),
                "sensor_model": str(r[2]),
                "type_name": str(r[3]),
                "category": str(r[4]),
                "unit": str(r[5]),
                "value": float(r[6]),
                "recorded_at": r[7],
                "source_type": str(r[8]) if len(r) > 8 and r[8] is not None else "auto",
                "is_limit_alert": bool(r[9]) if len(r) > 9 and r[9] is not None else False
            })
    else:
        for r in rows:
            prepared.append({
                "station": str(r[0]),
                "sensor_model": str(r[1]),
                "type_name": str(r[2]),
                "category": str(r[3]),
                "unit": str(r[4]),
                "value": float(r[5]),
                "recorded_at": r[6],
                "source_type": str(r[7]) if len(r) > 7 and r[7] is not None else "auto",
                "is_limit_alert": bool(r[8]) if len(r) > 8 and r[8] is not None else False
            })

    return prepared


def filter_rows_by_time(rows, time_start=None, time_end=None):
    if not time_start or not time_end:
        return rows

    return [row for row in rows if time_start <= row["recorded_at"].time() <= time_end]


def get_categories_from_rows(rows):
    result = []

    for row in rows:
        category = row["category"]

        if category not in result:
            result.append(category)

    return result


def average_rows_by_period(rows, period):
    buckets = {}

    for row in rows:
        dt = row["recorded_at"]

        if period == "10min":
            bucket_minute = (dt.minute // 10) * 10
            bucket = dt.replace(minute=bucket_minute, second=0, microsecond=0)
        elif period == "hour":
            bucket = dt.replace(minute=0, second=0, microsecond=0)
        else:
            bucket = dt

        key = (row["category"], row["unit"], bucket)

        if key not in buckets:
            buckets[key] = []

        buckets[key].append(row)

    averaged = []

    for (category, unit, bucket), values in buckets.items():
        averaged.append({
            "category": category,
            "unit": unit,
            "value": sum(row["value"] for row in values) / len(values),
            "recorded_at": bucket,
            "source_type": "manual_web" if any(row.get("source_type") == "manual_web" for row in values) else "manual_lcd" if any(row.get("source_type") == "manual_lcd" for row in values) else "auto",
            "has_manual": any(row.get("source_type") in ["manual_web", "manual_lcd"] for row in values),
            "is_limit_alert": any(row.get("is_limit_alert") for row in values)
        })

    averaged.sort(key=lambda x: (x["category"], x["recorded_at"]))
    return averaged


def average_rows_by_10_minutes(rows):
    return average_rows_by_period(rows, "10min")


def average_rows_by_hours(rows):
    return average_rows_by_period(rows, "hour")


def average_rows_by_days(rows):
    buckets = {}

    for row in rows:
        day = row["recorded_at"].date()
        key = (row["category"], row["unit"], day)

        if key not in buckets:
            buckets[key] = []

        buckets[key].append(row)

    averaged = []

    for (category, unit, day), values in buckets.items():
        averaged.append({
            "category": category,
            "unit": unit,
            "value": sum(row["value"] for row in values) / len(values),
            "recorded_at": datetime.combine(day, time(12, 0)),
            "day": day,
            "source_type": "manual_web" if any(row.get("source_type") == "manual_web" for row in values) else "manual_lcd" if any(row.get("source_type") == "manual_lcd" for row in values) else "auto",
            "has_manual": any(row.get("source_type") in ["manual_web", "manual_lcd"] for row in values),
            "is_limit_alert": any(row.get("is_limit_alert") for row in values)
        })

    averaged.sort(key=lambda x: (x["category"], x["recorded_at"]))
    return averaged


def get_period_bounds(data, period_start=None, period_end=None):
    if period_start and period_end:
        return period_start, period_end

    days = sorted(set(row["recorded_at"].date() for row in data))

    return days[0], days[-1]


def draw_period_graph(data, filename, mode="separate", selected_category=None, period_start=None, period_end=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        if selected_category:
            data = [row for row in data if row["category"] == selected_category]

            if not data:
                return None, "Нет данных по выбранному параметру"

        start_day, end_day = get_period_bounds(data, period_start, period_end)
        selected_days_count = (end_day - start_day).days + 1

        if selected_days_count <= 5:
            plot_data = average_rows_by_hours(data)
            title_mode = "среднее значение за каждый час"
            x_mode = "hourly"
        else:
            plot_data = average_rows_by_days(data)
            title_mode = "среднее значение за каждый день"
            x_mode = "daily"

        if not plot_data:
            return None, "Нет данных для построения графика"

        categories = get_categories_from_rows(plot_data)

        if mode == "single":
            categories = [selected_category]

        if mode == "separate":
            fig_height = max(4, 3.1 * len(categories))
            fig, axes = plt.subplots(len(categories), 1, figsize=(13, fig_height), sharex=True)

            if len(categories) == 1:
                axes = [axes]
        else:
            fig, axes = plt.subplots(1, 1, figsize=(13, 6))
            axes = [axes]

        for index, category in enumerate(categories):
            ax = axes[index] if mode == "separate" else axes[0]
            part = [row for row in plot_data if row["category"] == category]
            part.sort(key=lambda x: x["recorded_at"])

            if not part:
                continue

            x = [row["recorded_at"] for row in part]
            y = [row["value"] for row in part]
            unit = part[0]["unit"]
            label = f"{CATEGORY_RU.get(category, category)}, {unit}"

            ax.plot(x, y, marker="o", markersize=5, linewidth=1.5, label=label)

            manual_ok_points = [
                row for row in part
                if row.get("has_manual") and not row.get("is_limit_alert")
            ]

            alert_auto_points = [
                row for row in part
                if row.get("is_limit_alert") and not row.get("has_manual")
            ]

            manual_alert_points = [
                row for row in part
                if row.get("has_manual") and row.get("is_limit_alert")
            ]

            if manual_ok_points:
                ax.scatter(
                    [row["recorded_at"] for row in manual_ok_points],
                    [row["value"] for row in manual_ok_points],
                    s=65,
                    color="green",
                    edgecolors="black",
                    linewidths=0.5,
                    label="есть ручная отправка",
                    zorder=6
                )

            if alert_auto_points:
                ax.scatter(
                    [row["recorded_at"] for row in alert_auto_points],
                    [row["value"] for row in alert_auto_points],
                    s=80,
                    color="red",
                    edgecolors="black",
                    linewidths=0.5,
                    label="есть превышение лимита",
                    zorder=7
                )

            if manual_alert_points:
                ax.scatter(
                    [row["recorded_at"] for row in manual_alert_points],
                    [row["value"] for row in manual_alert_points],
                    s=95,
                    color="green",
                    edgecolors="red",
                    linewidths=2.0,
                    label="ручная отправка с превышением",
                    zorder=8
                )

            ax.set_title(CATEGORY_RU.get(category, category))
            ax.set_ylabel(unit)
            ax.grid(True, which="major", alpha=0.35, linewidth=0.8)
            ax.grid(True, which="minor", alpha=0.14, linewidth=0.5)
            ax.legend(loc="best")

            if y:
                y_min = min(y)
                y_max = max(y)

                if y_min == y_max:
                    delta = abs(y_min) * 0.05 if y_min != 0 else 1
                    ax.set_ylim(y_min - delta, y_max + delta)
                else:
                    delta = (y_max - y_min) * 0.08
                    ax.set_ylim(y_min - delta, y_max + delta)

        target_ax = axes[-1]
        target_ax.set_xlabel("Дата и время" if x_mode == "hourly" else "Дата")

        x_start = datetime.combine(start_day, time(0, 0))
        x_end = datetime.combine(end_day, time(23, 59))

        for ax in axes:
            ax.set_xlim(x_start, x_end)

            if x_mode == "hourly":
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:00"))
                ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
            else:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[12]))

        fig.autofmt_xdate(rotation=0 if x_mode == "hourly" else 30)
        fig.suptitle(f"Показания датчиков: {title_mode}", fontsize=14)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(filename, dpi=160)
        plt.close(fig)

        return filename, None

    except Exception as e:
        return None, f"Ошибка построения графика: {e}"


def draw_day_detail_graph(data, filename, mode="separate", selected_category=None, specific_date=None, time_start=None, time_end=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        if selected_category:
            data = [row for row in data if row["category"] == selected_category]

            if not data:
                return None, "Нет данных по выбранному параметру"

        if time_start and time_end:
            data = filter_rows_by_time(data, time_start, time_end)

            if not data:
                return None, "В выбранном промежутке времени нет показаний"

        important_data = [
            row for row in data
            if row.get("is_limit_alert") or row.get("source_type") in ["manual_web", "manual_lcd"]
        ]

        plot_data = average_rows_by_10_minutes(data)
        subtitle = "обычные данные усреднены за 10 минут, важные точки показаны отдельно"
        categories = get_categories_from_rows(data)

        if not categories:
            return None, "Нет параметров для построения"

        if mode == "single":
            categories = [selected_category]

        if mode == "separate":
            fig_height = max(4, 3.1 * len(categories))
            fig, axes = plt.subplots(len(categories), 1, figsize=(13, fig_height), sharex=True)

            if len(categories) == 1:
                axes = [axes]
        else:
            fig, axes = plt.subplots(1, 1, figsize=(13, 6))
            axes = [axes]

        for index, category in enumerate(categories):
            ax = axes[index] if mode == "separate" else axes[0]
            part = [row for row in plot_data if row["category"] == category]
            part.sort(key=lambda x: x["recorded_at"])

            if not part:
                continue

            x = [row["recorded_at"] for row in part]
            y = [row["value"] for row in part]
            unit = part[0]["unit"]
            label = f"{CATEGORY_RU.get(category, category)}, {unit}"

            marker = "o" if len(part) <= 200 else "."
            line_width = 1.4 if len(part) <= 300 else 0.9

            ax.plot(x, y, marker=marker, markersize=4, linewidth=line_width, label=label)

            important_part = [row for row in important_data if row["category"] == category]

            manual_ok_points = [
                row for row in important_part
                if row.get("source_type") in ["manual_web", "manual_lcd"] and not row.get("is_limit_alert")
            ]

            alert_auto_points = [
                row for row in important_part
                if row.get("is_limit_alert") and row.get("source_type") not in ["manual_web", "manual_lcd"]
            ]

            manual_alert_points = [
                row for row in important_part
                if row.get("source_type") in ["manual_web", "manual_lcd"] and row.get("is_limit_alert")
            ]

            if manual_ok_points:
                ax.scatter(
                    [row["recorded_at"] for row in manual_ok_points],
                    [row["value"] for row in manual_ok_points],
                    s=58,
                    color="green",
                    edgecolors="black",
                    linewidths=0.5,
                    label="ручная отправка",
                    zorder=6
                )

            if alert_auto_points:
                ax.scatter(
                    [row["recorded_at"] for row in alert_auto_points],
                    [row["value"] for row in alert_auto_points],
                    s=70,
                    color="red",
                    edgecolors="black",
                    linewidths=0.5,
                    label="превышение лимита",
                    zorder=7
                )

            if manual_alert_points:
                ax.scatter(
                    [row["recorded_at"] for row in manual_alert_points],
                    [row["value"] for row in manual_alert_points],
                    s=90,
                    color="green",
                    edgecolors="red",
                    linewidths=2.0,
                    label="ручная отправка с превышением",
                    zorder=8
                )

            ax.set_title(CATEGORY_RU.get(category, category))
            ax.set_ylabel(unit)
            ax.grid(True, which="major", alpha=0.35, linewidth=0.8)
            ax.grid(True, which="minor", alpha=0.16, linewidth=0.5)
            ax.legend(loc="best")

            all_y = y + [row["value"] for row in important_part]

            if all_y:
                y_min = min(all_y)
                y_max = max(all_y)

                if y_min == y_max:
                    delta = abs(y_min) * 0.05 if y_min != 0 else 1
                    ax.set_ylim(y_min - delta, y_max + delta)
                else:
                    delta = (y_max - y_min) * 0.08
                    ax.set_ylim(y_min - delta, y_max + delta)

        target_ax = axes[-1]
        target_ax.set_xlabel("Время")

        base_day = specific_date or data[0]["recorded_at"].date()

        if time_start and time_end:
            x_start = datetime.combine(base_day, time_start)
            x_end = datetime.combine(base_day, time_end)
        else:
            x_start = datetime.combine(base_day, time(0, 0))
            x_end = x_start + timedelta(days=1)

        for ax in axes:
            ax.set_xlim(x_start, x_end)
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
            ax.xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[10, 20, 30, 40, 50]))

        fig.autofmt_xdate(rotation=0)
        title_period = base_day.strftime("%d.%m.%Y")

        if time_start and time_end:
            title_period += f" {time_start.strftime('%H:%M')}–{time_end.strftime('%H:%M')}"

        fig.suptitle(f"Показания датчиков: {title_period}, {subtitle}", fontsize=14)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(filename, dpi=160)
        plt.close(fig)

        return filename, None

    except Exception as e:
        return None, f"Ошибка построения графика: {e}"


def create_sensor_graph(
    rows,
    user_id,
    filename,
    mode="separate",
    selected_category=None,
    specific_date=None,
    time_start=None,
    time_end=None,
    average_10min=False,
    period_start=None,
    period_end=None
):
    data = normalize_rows(rows, user_id)

    if not data:
        return None, "Нет данных для графика"

    if specific_date is not None:
        return draw_day_detail_graph(
            data,
            filename,
            mode=mode,
            selected_category=selected_category,
            specific_date=specific_date,
            time_start=time_start,
            time_end=time_end
        )

    return draw_period_graph(
        data,
        filename,
        mode=mode,
        selected_category=selected_category,
        period_start=period_start,
        period_end=period_end
    )
