from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

# Wrapper for Weather Service (OpenWeatherMap)
# https://openweathermap.org/api

# Local cache to avoid frequent geocoding calls
GEO_CACHE: Dict[str, Dict[str, Any]] = {
    # Miá»n Báº¯c
    "VN-HN": {"lat": 21.0285, "lon": 105.8542, "name": "HĂ  Ná»™i"},
    "HĂ  Ná»™i": {"lat": 21.0285, "lon": 105.8542, "name": "HĂ  Ná»™i"},
    "VN-27": {"lat": 21.1667, "lon": 106.0500, "name": "Báº¯c Ninh"},
    # Miá»n Trung
    "VN-26": {"lat": 16.0544, "lon": 108.2022, "name": "ÄĂ  Náºµng"},
    # Miá»n Nam
    "VN-SG": {"lat": 10.8231, "lon": 106.6297, "name": "TP.HCM"},
    "VN-63": {"lat": 10.0333, "lon": 105.7833, "name": "Cáº§n ThÆ¡"},
    "VN-57": {"lat": 10.2500, "lon": 105.9667, "name": "VÄ©nh Long"},
}

async def _get_coordinates(geo_name: str, api_key: str) -> Optional[Tuple[float, float, str]]:
    """
    Get latitude and longitude from location name using OpenWeatherMap Geocoding API.
    """
    url = "https://api.openweathermap.org/geo/1.0/direct"
    # Append Vietnam country code to help accuracy
    query = f"{geo_name},VN" if "," not in geo_name else geo_name
    
    params = {
        "q": query,
        "limit": 1,
        "appid": api_key
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            if data and isinstance(data, list) and len(data) > 0:
                first_result = data[0]
                lat = first_result.get("lat")
                lon = first_result.get("lon")
                name = first_result.get("local_names", {}).get("vi") or first_result.get("name") or geo_name
                return lat, lon, name
            return None
    except Exception as e:
        logger.error(f"Geocoding Error for '{geo_name}': {e}")
        return None

async def weather_api(geo_code: str, days: int = 7) -> Optional[Dict[str, Any]]:
    """
    Fetch weather forecast from OpenWeatherMap (Forecast 2.5) with dynamic geocoding.
    
    returns: {
      "location": str,
      "updated_at": str,
      "summary": str,
      "source_url": str
    }
    """
    api_key = settings.OPENWEATHER_API_KEY
    if not api_key:
        logger.warning("OPENWEATHER_API_KEY is not set. Returning None.")
        return None
    try:
        requested_days = int(days)
    except (TypeError, ValueError):
        requested_days = 3
    requested_days = max(1, min(requested_days, 5))

    # 1. Resolve Coords (Check Cache first, then Geocoding API)
    lat, lon, location_name = None, None, geo_code
    
    if geo_code in GEO_CACHE:
        loc_info = GEO_CACHE[geo_code]
        lat, lon, location_name = loc_info["lat"], loc_info["lon"], loc_info["name"]
    else:
        # Avoid geocoding empty strings or generic placeholders
        if geo_code and geo_code.strip() and geo_code.lower() not in ["null", "none", "unknown"]:
            geo_result = await _get_coordinates(geo_code, api_key)
            if geo_result:
                lat, lon, location_name = geo_result
                # Update cache in-memory for next time
                GEO_CACHE[geo_code] = {"lat": lat, "lon": lon, "name": location_name}

    if lat is None or lon is None:
        logger.warning(f"Unable to geocode '{geo_code}', utilizing default fallback to Hanoi.")
        lat, lon = 21.0285, 105.8542 
        location_name = f"HĂ  Ná»™i (Máº·c Ä‘á»‹nh do khĂ´ng tĂ¬m tháº¥y {geo_code})"

    # 2. Call API (5 day / 3 hour forecast is standard free tier)
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": "vi"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            # 3. Process Data (respect requested days, max ~5 days on free tier)
            raw_forecasts = data.get("list", []) or []
            forecasts = raw_forecasts[: requested_days * 8]  # 8 points/day (3-hour interval)

            target_dates = []
            for pd in forecasts:
                dt_txt = pd.get("dt_txt", "")
                if " " not in dt_txt:
                    continue
                date_val = dt_txt.split(" ", 1)[0]
                if date_val and date_val not in target_dates:
                    target_dates.append(date_val)
                if len(target_dates) >= requested_days:
                    break
            target_date_set = set(target_dates)

            summary_parts = []
            for pd in forecasts:
                dt_txt = pd.get("dt_txt", "")
                if " " not in dt_txt:
                    continue
                date_val, time_val = dt_txt.split(" ", 1)
                if target_date_set and date_val not in target_date_set:
                    continue
                if time_val not in ("12:00:00", "00:00:00"):
                    continue

                main = pd.get("main", {})
                weather = pd.get("weather", [{}])[0]
                temp = main.get("temp")
                desc = weather.get("description")
                humidity = main.get("humidity", "")

                time_label = "Noon" if time_val == "12:00:00" else "Night"
                summary_parts.append(f"{date_val} ({time_label}): {desc}, Temp {temp}C, Humidity {humidity}%")

            if not summary_parts and forecasts:
                first = forecasts[0]
                dt_txt = first.get("dt_txt", "")
                main = first.get("main", {})
                weather = first.get("weather", [{}])[0]
                summary_parts.append(
                    f"{dt_txt}: {weather.get('description')}, Temp {main.get('temp')}C, Humidity {main.get('humidity', '')}%"
                )
            full_summary = " | ".join(summary_parts) if summary_parts else "KhĂ´ng cĂ³ bĂ¡o cĂ¡o chi tiáº¿t."
            
            return {
                "location": f"{location_name}",
                "updated_at": "Hiá»‡n táº¡i",
                "summary": f"Dá»± bĂ¡o thá»i tiáº¿t tĂ³m táº¯t: {full_summary}",
                "source_url": f"https://openweathermap.org/city/{data.get('city', {}).get('id')}"
            }

    except Exception as e:
        logger.error(f"OpenWeatherMap Error: {e}")
        return None
