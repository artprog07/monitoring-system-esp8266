import os
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def build_sensor_graph(
    rows,
    output_dir="reports",
    days=1,
    title="Показания датчиков",
    filename_prefix="readings_graph"
):
    """
    rows — список словарей или DataFrame с колонками:
        recorded_at
        type_name
        value
        unit
        source_type
        is_limit_alert

    Пример строки:
    {
        "recorded_at": datetime,
        "type_name": "Температура",
        "value": 27.5,
        "unit": "C",
        "source_type": "auto",
        "is_limit_alert": False
    }
    """

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    df = pd.DataFrame(rows)

    if df.empty:
        return None

    required_columns = {
        "recorded_at",
        "type_name",
        "value",
        "unit",
        "source_type",
        "is_limit_alert"
    }

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Не хватает колонок для графика: {missing}")

    df["recorded_at"] = pd.to_datetime(df["recorded_at"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["recorded_at", "value"])

    if df.empty:
        return None

    df["is_limit_alert"] = df["is_limit_alert"].fillna(False).astype(bool)
    df["is_manual"] = df["source_type"].isin(["manual_lcd", "manual_web"])

    # Определяем интервал агрегации
    if days <= 1:
        freq = "10min"
        x_format = "%H:%M"
        x_label = "Время"
    elif 2 <= days <= 5:
        freq = "1h"
        x_format = "%d.%m %H:%M"
        x_label = "Дата и время"
    else:
        freq = "1D"
        x_format = "%d.%m"
        x_label = "Дата"

    df["time_bucket"] = df["recorded_at"].dt.floor(freq)

    # Агрегируем значения и одновременно сохраняем признаки событий
    plot_df = (
        df.groupby(["type_name", "unit", "time_bucket"], as_index=False)
          .agg(
              value=("value", "mean"),
              has_alert=("is_limit_alert", "max"),
              has_manual=("is_manual", "max")
          )
    )

    sensor_types = list(plot_df["type_name"].dropna().unique())

    if not sensor_types:
        return None

    fig_height = max(3.2 * len(sensor_types), 4)
    fig, axes = plt.subplots(
        nrows=len(sensor_types),
        ncols=1,
        figsize=(14, fig_height),
        sharex=False
    )

    if len(sensor_types) == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=16)

    for ax, sensor_type in zip(axes, sensor_types):
        sensor_df = plot_df[plot_df["type_name"] == sensor_type].copy()
        sensor_df = sensor_df.sort_values("time_bucket")

        if sensor_df.empty:
            continue

        unit = sensor_df["unit"].iloc[0]

        # Основная синяя линия строится по ВСЕМ агрегированным точкам
        ax.plot(
            sensor_df["time_bucket"],
            sensor_df["value"],
            marker="o",
            linewidth=1.8,
            markersize=4,
            label=f"{sensor_type}, {unit}"
        )

        # Только превышение лимита
        alert_points = sensor_df[
            (sensor_df["has_alert"] == True) &
            (sensor_df["has_manual"] == False)
        ]

        if not alert_points.empty:
            ax.scatter(
                alert_points["time_bucket"],
                alert_points["value"],
                s=70,
                color="red",
                edgecolors="black",
                linewidths=0.8,
                zorder=6,
                label="превышение лимита"
            )

        # Только ручная отправка
        manual_points = sensor_df[
            (sensor_df["has_manual"] == True) &
            (sensor_df["has_alert"] == False)
        ]

        if not manual_points.empty:
            ax.scatter(
                manual_points["time_bucket"],
                manual_points["value"],
                s=70,
                color="green",
                edgecolors="black",
                linewidths=0.8,
                zorder=6,
                label="ручная отправка"
            )

        # Ручная отправка + превышение
        both_points = sensor_df[
            (sensor_df["has_manual"] == True) &
            (sensor_df["has_alert"] == True)
        ]

        if not both_points.empty:
            ax.scatter(
                both_points["time_bucket"],
                both_points["value"],
                s=85,
                color="green",
                edgecolors="red",
                linewidths=2,
                zorder=7,
                label="ручная отправка + превышение"
            )

        ax.set_title(sensor_type)
        ax.set_ylabel(unit)
        ax.set_xlabel(x_label)

        # Ось X дублируется на каждом графике
        ax.tick_params(axis="x", labelbottom=True, labelrotation=45)

        ax.xaxis.set_major_formatter(mdates.DateFormatter(x_format))

        # Дополнительные мелкие деления по X
        if days <= 1:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
            ax.xaxis.set_minor_locator(mdates.MinuteLocator(interval=10))
        elif 2 <= days <= 5:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        else:
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))

        ax.grid(True, which="major", alpha=0.35)
        ax.grid(True, which="minor", alpha=0.15)

        ax.legend(loc="best", fontsize=9)

    fig.tight_layout(rect=[0, 0, 1, 0.96])

    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(output_dir, f"{filename_prefix}_{now_str}.png")

    fig.savefig(file_path, dpi=160, bbox_inches="tight")
    plt.close(fig)

    return file_path