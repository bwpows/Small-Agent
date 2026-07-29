"""
天气查询工具
---------------
使用 Open-Meteo 免费 API，无需 API Key。
支持当前天气 + 未来预报（最多 16 天）。
"""

import datetime
import requests


# ---- 天气代码中文映射 ----
WMO_CODE_MAP = {
    0:  "晴天",
    1:  "大部晴朗",
    2:  "多云",
    3:  "阴天",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _get_coordinates(location: str) -> dict:
    """通过城市名获取经纬度。"""
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "zh"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {}
        r = results[0]
        return {
            "name": r.get("name", location),
            "country": r.get("country", ""),
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "timezone": r.get("timezone", "auto"),
        }
    except Exception:
        return {}


def _format_current(c: dict, geo: dict) -> str:
    """格式化当前天气。"""
    temp = c.get("temperature_2m", "N/A")
    feels_like = c.get("apparent_temperature", "N/A")
    humidity = c.get("relative_humidity_2m", "N/A")
    wind_speed = c.get("wind_speed_10m", "N/A")
    code = c.get("weather_code", -1)
    desc = WMO_CODE_MAP.get(code, f"未知代码({code})")

    city_display = (
        f"{geo['name']}, {geo['country']}"
        if geo.get("country")
        else geo["name"]
    )

    return (
        f"📍 **{city_display}** 当前天气\n"
        f"{'─' * 25}\n"
        f"🌡️  气温：{temp}°C（体感 {feels_like}°C）\n"
        f"🌤️  天气：{desc}\n"
        f"💧 湿度：{humidity}%\n"
        f"💨 风速：{wind_speed} km/h\n"
        f"{'─' * 25}\n"
        f"数据来源：Open-Meteo（免费开放数据）"
    )


def _format_daily(day_data: dict, date_label: str, geo: dict) -> str:
    """格式化单天预报。"""
    code = day_data.get("weather_code", -1)
    desc = WMO_CODE_MAP.get(code, f"未知代码({code})")
    t_max = day_data.get("temperature_2m_max", "N/A")
    t_min = day_data.get("temperature_2m_min", "N/A")
    precip = day_data.get("precipitation_sum", "N/A")
    prob = day_data.get("precipitation_probability_max", "N/A")
    wind = day_data.get("wind_speed_10m_max", "N/A")
    uv = day_data.get("uv_index_max", "N/A")

    city_display = geo["name"]

    return (
        f"📍 **{city_display}** {date_label} 预报\n"
        f"{'─' * 25}\n"
        f"🌤️  天气：{desc}\n"
        f"🌡️  温度：{t_min}°C ~ {t_max}°C\n"
        f"☔ 降水：{precip} mm（概率 {prob}%）\n"
        f"💨 最大风速：{wind} km/h\n"
        f"🔆 紫外线：{uv}\n"
        f"{'─' * 25}\n"
        f"数据来源：Open-Meteo（免费开放数据）"
    )


def _format_week(daily: dict, geo: dict) -> str:
    """格式化 7 天概览。"""
    city_display = geo["name"]
    lines = [f"📍 **{city_display}** 未来 7 天天气概览\n" + "─" * 30]

    dates = daily.get("time", [])
    codes = daily.get("weather_code", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    prob = daily.get("precipitation_probability_max", [])

    today = datetime.date.today()
    for i, date_str in enumerate(dates[:7]):
        try:
            d = datetime.date.fromisoformat(date_str)
            label = "今天" if d == today else (
                "明天" if d == today + datetime.timedelta(days=1)
                else d.strftime("%m月%d日")
            )
        except Exception:
            label = date_str

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        try:
            d_obj = datetime.date.fromisoformat(date_str)
            weekday = weekday_names[d_obj.weekday()]
        except Exception:
            weekday = ""

        code = codes[i] if i < len(codes) else -1
        desc = WMO_CODE_MAP.get(code, "?")
        tmx = t_max[i] if i < len(t_max) else "N/A"
        tmn = t_min[i] if i < len(t_min) else "N/A"
        pr = precip[i] if i < len(precip) else "N/A"
        pp = prob[i] if i < len(prob) else "N/A"

        lines.append(
            f"📅 **{label}**（{weekday}）\n"
            f"   {desc}　{tmn}~{tmx}°C　降水{pr}mm（{pp}%）"
        )

    lines.append("─" * 30)
    lines.append("数据来源：Open-Meteo（免费开放数据）")
    return "\n".join(lines)


def get_weather(location: str, day: str = "today") -> str:
    """
    查询指定城市的天气。
    参数:
      location: 城市名（中文/英文均可），如「北京」「Tokyo」
      day:
        - "today"（默认）→ 当前天气
        - "tomorrow" → 明天预报
        - "day_after_tomorrow" → 后天预报
        - "week" → 未来 7 天概览
        - "1" ~ "16" → 未来第 N 天的预报
    """
    if not location or not location.strip():
        return "❌ 请提供要查询的城市名称，例如：北京、上海、Tokyo。"

    location = location.strip()
    day = (day or "today").strip().lower()

    # 地理编码
    geo = _get_coordinates(location)
    if not geo:
        return (
            f"❌ 未找到城市「{location}」的天气信息。\n"
            "建议：请使用城市标准名称重试，例如「北京」「上海」「Tokyo」「New York」。"
        )

    try:
        # 当前天气
        if day == "today":
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "current": (
                        "temperature_2m,relative_humidity_2m,"
                        "weather_code,wind_speed_10m,"
                        "apparent_temperature"
                    ),
                    "timezone": geo["timezone"],
                },
                timeout=10,
            )
            resp.raise_for_status()
            return _format_current(resp.json().get("current", {}), geo)

        # 未来预报（共用 daily 接口）
        params = {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,precipitation_probability_max,"
                "wind_speed_10m_max,uv_index_max"
            ),
            "timezone": geo["timezone"],
            "forecast_days": 16,
        }

        if day == "week":
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return _format_week(resp.json().get("daily", {}), geo)

        # 具体某天
        index_map = {"tomorrow": 0, "day_after_tomorrow": 1}
        if day in index_map:
            idx = index_map[day]
            label = "明天" if day == "tomorrow" else "后天"
        elif day.isdigit():
            idx = int(day) - 1
            if idx < 0 or idx > 15:
                return "❌ day 参数范围为 1~16。"
            d = datetime.date.today() + datetime.timedelta(days=idx + 1)
            label = d.strftime("%m月%d日")
        else:
            return (
                "❌ day 参数无效。请使用：\n"
                "- today（当前）\n"
                "- tomorrow（明天）\n"
                "- day_after_tomorrow（后天）\n"
                "- week（未来 7 天概览）\n"
                "- 1~16（具体天数）"
            )

        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        daily = resp.json().get("daily", {})

        # 提取对应索引的那一天
        day_data = {}
        for key, vals in daily.items():
            if isinstance(vals, list) and idx < len(vals):
                day_data[key] = vals[idx]
            else:
                day_data[key] = "N/A"

        return _format_daily(day_data, label, geo)

    except Exception as e:
        return f"❌ 天气查询失败: {str(e)}"


# ======= 动态路由注册声明 =======
REGISTER_NAME = "get_weather"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "查询指定城市的天气，支持当前天气和未来预报。\n"
            "参数 day 用法：\n"
            "- today（默认）：当前实时天气\n"
            "- tomorrow：明天预报\n"
            "- day_after_tomorrow：后天预报\n"
            "- week：未来 7 天概览\n"
            "- 1~16：第 N 天的预报（如 3 表示 3 天后）\n"
            "返回：温度范围、天气状况、降水概率与降水量、风速、紫外线指数等。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "城市名称，支持中文或英文。"
                        "例如：北京、上海、深圳、Tokyo、New York、London。"
                    ),
                },
                "day": {
                    "type": "string",
                    "description": (
                        "查询的时间范围："
                        "「today」= 当前；"
                        "「tomorrow」= 明天；"
                        "「day_after_tomorrow」= 后天；"
                        "「week」= 未来 7 天概览；"
                        "「1」~「16」= 第 N 天。"
                        "用户问「今天/现在」用 today；"
                        "问「明天/后天」用 tomorrow/day_after_tomorrow；"
                        "问「这周/最近几天」用 week。"
                    ),
                    "enum": [
                        "today", "tomorrow", "day_after_tomorrow",
                        "week", "1", "2", "3", "4", "5", "6", "7",
                        "8", "9", "10", "11", "12", "13", "14", "15", "16",
                    ],
                    "default": "today",
                },
            },
            "required": ["location"],
        },
    },
}