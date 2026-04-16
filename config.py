import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")


def _load_env_file(path):
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]

                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_env_file(os.path.join(BASE_DIR, ".env.supabase"))

DB_PATH = os.path.join(BASE_DIR, "data", "smart_pos.db")
SCALE_CONFIG_PATH = os.path.join(BASE_DIR, "data", "scale_config.txt")

DATASET_DIR = os.path.abspath(
    os.path.expanduser(
        os.getenv("SMARTPOS_DATASET_DIR", os.path.join(BASE_DIR, "data", "dataset"))
    )
)

PROFILES_PATH = os.path.abspath(
    os.path.expanduser(
        os.getenv("SMARTPOS_PROFILES_PATH", os.path.join(BASE_DIR, "recognition_profiles.pkl"))
    )
)

MOBILENET_WEIGHTS_PATH = os.path.abspath(
    os.path.expanduser(os.getenv("SMARTPOS_MOBILENET_WEIGHTS_PATH", ""))
) if os.getenv("SMARTPOS_MOBILENET_WEIGHTS_PATH") else ""

AI_ALLOW_ONLINE_WEIGHTS = os.getenv("SMARTPOS_ALLOW_ONLINE_WEIGHTS", "1").strip().lower() not in {
    "0",
    "false",
    "no"
}


def _env_float(name, default):
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return float(default)


_profile_raw = str(os.getenv("SMARTPOS_AI_PROFILE", "strict")).strip().lower()
AI_RECOGNITION_PROFILE = _profile_raw if _profile_raw in {"strict", "balanced"} else "strict"

_PROFILE_DEFAULTS = {
    "strict": {
        "AI_INFERENCE_INTERVAL": 2,
        "AI_FAST_LOCK_MIN_CONFIDENCE": 0.92,
        "AI_SWITCH_LABEL_MIN_CONFIDENCE": 0.96,
        "AI_SWITCH_LABEL_MIN_VOTES": 3,
        "AI_SWITCH_REQUIRED_CONSECUTIVE": 2,
        "AI_MIN_LOCK_HOLD_SECONDS": 0.70,
        "AI_WEIGHT_CHANGE_THRESHOLD_KG": 0.03,
        "AI_WEIGHT_TRANSITION_WINDOW_S": 1.20,
        "AI_WEIGHT_EMPTY_THRESHOLD_KG": 0.008,
    },
    "balanced": {
        "AI_INFERENCE_INTERVAL": 2,
        "AI_FAST_LOCK_MIN_CONFIDENCE": 0.90,
        "AI_SWITCH_LABEL_MIN_CONFIDENCE": 0.94,
        "AI_SWITCH_LABEL_MIN_VOTES": 2,
        "AI_SWITCH_REQUIRED_CONSECUTIVE": 1,
        "AI_MIN_LOCK_HOLD_SECONDS": 0.45,
        "AI_WEIGHT_CHANGE_THRESHOLD_KG": 0.025,
        "AI_WEIGHT_TRANSITION_WINDOW_S": 1.00,
        "AI_WEIGHT_EMPTY_THRESHOLD_KG": 0.008,
    },
}

_active_profile = _PROFILE_DEFAULTS[AI_RECOGNITION_PROFILE]
AI_INFERENCE_INTERVAL = max(1, int(_env_float("SMARTPOS_AI_INFERENCE_INTERVAL", _active_profile["AI_INFERENCE_INTERVAL"])))
AI_FAST_LOCK_MIN_CONFIDENCE = min(0.999, max(0.50, _env_float("SMARTPOS_AI_FAST_LOCK_MIN_CONFIDENCE", _active_profile["AI_FAST_LOCK_MIN_CONFIDENCE"])))
AI_SWITCH_LABEL_MIN_CONFIDENCE = min(0.999, max(0.50, _env_float("SMARTPOS_AI_SWITCH_LABEL_MIN_CONFIDENCE", _active_profile["AI_SWITCH_LABEL_MIN_CONFIDENCE"])))
AI_SWITCH_LABEL_MIN_VOTES = max(1, int(_env_float("SMARTPOS_AI_SWITCH_LABEL_MIN_VOTES", _active_profile["AI_SWITCH_LABEL_MIN_VOTES"])))
AI_SWITCH_REQUIRED_CONSECUTIVE = max(1, int(_env_float("SMARTPOS_AI_SWITCH_REQUIRED_CONSECUTIVE", _active_profile["AI_SWITCH_REQUIRED_CONSECUTIVE"])))
AI_MIN_LOCK_HOLD_SECONDS = max(0.0, _env_float("SMARTPOS_AI_MIN_LOCK_HOLD_SECONDS", _active_profile["AI_MIN_LOCK_HOLD_SECONDS"]))
AI_WEIGHT_CHANGE_THRESHOLD_KG = max(0.001, _env_float("SMARTPOS_AI_WEIGHT_CHANGE_THRESHOLD_KG", _active_profile["AI_WEIGHT_CHANGE_THRESHOLD_KG"]))
AI_WEIGHT_TRANSITION_WINDOW_S = max(0.2, _env_float("SMARTPOS_AI_WEIGHT_TRANSITION_WINDOW_S", _active_profile["AI_WEIGHT_TRANSITION_WINDOW_S"]))
AI_WEIGHT_EMPTY_THRESHOLD_KG = max(0.0, _env_float("SMARTPOS_AI_WEIGHT_EMPTY_THRESHOLD_KG", _active_profile["AI_WEIGHT_EMPTY_THRESHOLD_KG"]))

PRINTER_NAME = "POS-58"
SCALE_REFERENCE_UNIT = 6851.569090909091

# Scale jitter control (kg)
# These defaults are conservative for produce POS and can be tuned per device.
SCALE_MEDIAN_WINDOW = 5
SCALE_STABILITY_WINDOW = 8
SCALE_SMOOTHING_ALPHA = 0.35
SCALE_ZERO_THRESHOLD_KG = 0.0020
SCALE_DEADBAND_KG = 0.0015
SCALE_STABLE_RANGE_KG = 0.0020
SCALE_JUMP_THRESHOLD_KG = 0.0080

THEME_COLOR = "#2c3e50"
ACCENT_COLOR = "#2980b9"
TEXT_COLOR = "#ecf0f1"
WARNING_COLOR = "#e67e22"
DANGER_COLOR = "#c0392b"
SUCCESS_COLOR = "#27ae60"

FONT_MAIN = ("Segoe UI", 12)
FONT_HEADER = ("Segoe UI", 24, "bold")

SCREEN_MAIN_W = 1280
SCREEN_MAIN_H = 800

TASKBAR_H = 36

SCREEN_CUST_W = 1024
SCREEN_CUST_H = 600

CUSTOMER_OFFSET_X = 1280 
CUSTOMER_OFFSET_Y = 0

def _env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name, default):
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return default

CLOUD_SYNC_ENABLED = _env_bool("SMARTPOS_CLOUD_SYNC_ENABLED", False)
CLOUD_SYNC_ENDPOINT = str(os.getenv("SMARTPOS_CLOUD_SYNC_ENDPOINT", "")).strip()
CLOUD_SYNC_API_KEY = str(os.getenv("SMARTPOS_CLOUD_SYNC_API_KEY", "")).strip()
CLOUD_SYNC_INTERVAL_SECONDS = max(3, _env_int("SMARTPOS_CLOUD_SYNC_INTERVAL_SECONDS", 10))
CLOUD_SYNC_TIMEOUT_SECONDS = max(3, _env_int("SMARTPOS_CLOUD_SYNC_TIMEOUT_SECONDS", 8))
CLOUD_SYNC_BATCH_SIZE = max(1, _env_int("SMARTPOS_CLOUD_SYNC_BATCH_SIZE", 25))
CLOUD_SYNC_MAX_RETRIES = max(1, _env_int("SMARTPOS_CLOUD_SYNC_MAX_RETRIES", 10))
CLOUD_AUTO_START_LOCAL_RECEIVER = _env_bool("SMARTPOS_AUTO_START_LOCAL_RECEIVER", False)
CLOUD_LOCAL_RECEIVER_HOST = str(os.getenv("SMARTPOS_LOCAL_RECEIVER_HOST", "127.0.0.1")).strip() or "127.0.0.1"
CLOUD_LOCAL_RECEIVER_PORT = max(1, _env_int("SMARTPOS_LOCAL_RECEIVER_PORT", 8080))

