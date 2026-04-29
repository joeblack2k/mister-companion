from core.language import tr


RESOLUTION_MAP = {
    "0": "1280x720@60",
    "1": "1024x768@60",
    "2": "720x480@60",
    "3": "720x576@50",
    "4": "1280x1024@60",
    "5": "800x600@60",
    "6": "640x480@60",
    "7": "1280x720@50",
    "8": "1920x1080@60",
    "9": "1920x1080@50",
    "10": "1366x768@60",
    "11": "1024x600@60",
    "12": "1920x1440@60",
    "13": "2048x1536@60",
    "14": "2560x1440@60",
}

RESOLUTION_REVERSE_MAP = {value: key for key, value in RESOLUTION_MAP.items()}

SCALING_KEYS = {
    "0": "disabled",
    "1": "low_latency",
    "2": "exact_refresh",
}

DEFAULT_FONT_LINE = ";font=font/myfont.pf"


def scaling_label(value: str) -> str:
    labels = {
        "disabled": tr("mister_settings_tab.option_disabled"),
        "low_latency": tr("mister_settings_tab.option_low_latency"),
        "exact_refresh": tr("mister_settings_tab.option_exact_refresh"),
    }
    return labels.get(value, value)


def hdmi_mode_label(value: str) -> str:
    labels = {
        "hd_output": tr("mister_settings_tab.option_hd_output"),
        "direct_video": tr("mister_settings_tab.option_direct_video"),
    }
    return labels.get(value, value)


def hdmi_audio_label(value: str) -> str:
    labels = {
        "enabled": tr("mister_settings_tab.option_enabled"),
        "disabled_dvi": tr("mister_settings_tab.option_disabled_dvi"),
    }
    return labels.get(value, value)


def enabled_disabled_label(enabled: bool) -> str:
    return tr("mister_settings_tab.option_enabled") if enabled else tr("mister_settings_tab.option_disabled")


def hdmi_range_label(value: str) -> str:
    labels = {
        "full": tr("mister_settings_tab.option_full_range"),
        "limited": tr("mister_settings_tab.option_limited_range"),
    }
    return labels.get(value, value)


def analogue_label(value: str) -> str:
    labels = {
        "rgb_consumer": tr("mister_settings_tab.option_rgb_consumer"),
        "rgb_pvm": tr("mister_settings_tab.option_rgb_pvm"),
        "component": tr("mister_settings_tab.option_component"),
        "svideo": tr("mister_settings_tab.option_svideo"),
        "vga": tr("mister_settings_tab.option_vga_monitor"),
    }
    return labels.get(value, value)


def default_font_label() -> str:
    return tr("mister_settings_tab.default_font")


def _reverse_lookup(label: str, options: dict) -> str:
    value = (label or "").strip()

    for key, translated in options.items():
        if value == translated:
            return key

    for key in options:
        if value == key:
            return key

    return value


def hdmi_mode_key(label: str) -> str:
    return _reverse_lookup(label, {
        "hd_output": hdmi_mode_label("hd_output"),
        "direct_video": hdmi_mode_label("direct_video"),
    })


def scaling_key(label: str) -> str:
    return _reverse_lookup(label, {
        "disabled": scaling_label("disabled"),
        "low_latency": scaling_label("low_latency"),
        "exact_refresh": scaling_label("exact_refresh"),
    })


def hdmi_audio_key(label: str) -> str:
    return _reverse_lookup(label, {
        "enabled": hdmi_audio_label("enabled"),
        "disabled_dvi": hdmi_audio_label("disabled_dvi"),
    })


def enabled_disabled_key(label: str) -> str:
    return _reverse_lookup(label, {
        "enabled": tr("mister_settings_tab.option_enabled"),
        "disabled": tr("mister_settings_tab.option_disabled"),
    })


def hdmi_range_key(label: str) -> str:
    return _reverse_lookup(label, {
        "full": hdmi_range_label("full"),
        "limited": hdmi_range_label("limited"),
    })


def analogue_key(label: str) -> str:
    return _reverse_lookup(label, {
        "rgb_consumer": analogue_label("rgb_consumer"),
        "rgb_pvm": analogue_label("rgb_pvm"),
        "component": analogue_label("component"),
        "svideo": analogue_label("svideo"),
        "vga": analogue_label("vga"),
    })


def parse_mister_ini(text):
    settings = {}
    current_section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue

        if current_section != "MiSTer":
            continue

        if line.startswith(";"):
            comment_body = line[1:].strip()
            if "=" in comment_body:
                key, value = comment_body.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "font":
                    settings["font_commented"] = value
            continue

        if ";" in line:
            line = line.split(";", 1)[0].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip()

    return settings


def easy_mode_values_from_ini_settings(settings):
    values = {}

    direct_video = settings.get("direct_video", "0").strip()
    values["hdmi_mode"] = (
        hdmi_mode_label("direct_video")
        if direct_video in ("1", "2")
        else hdmi_mode_label("hd_output")
    )

    video_mode = settings.get("video_mode", "").strip()
    values["resolution"] = RESOLUTION_MAP.get(video_mode, "1920x1080@60")

    scaling_key_value = SCALING_KEYS.get(
        settings.get("vsync_adjust", "1").strip(),
        "low_latency",
    )
    values["scaling"] = scaling_label(scaling_key_value)

    dvi = settings.get("dvi_mode", "0").strip()
    values["hdmi_audio"] = (
        hdmi_audio_label("disabled_dvi")
        if dvi == "1"
        else hdmi_audio_label("enabled")
    )

    hdr = settings.get("hdr", "0").strip()
    values["hdr"] = enabled_disabled_label(hdr == "1")

    limited = settings.get("hdmi_limited", "0").strip()
    values["hdmi_limited"] = (
        hdmi_range_label("limited")
        if limited == "1"
        else hdmi_range_label("full")
    )

    vga_mode = settings.get("vga_mode", "rgb").strip().lower()
    composite_sync = settings.get("composite_sync", "0").strip()
    vga_sog = settings.get("vga_sog", "0").strip()

    if vga_mode == "ypbpr":
        values["analogue"] = analogue_label("component")
    elif vga_mode == "svideo":
        values["analogue"] = analogue_label("svideo")
    elif vga_mode == "rgb":
        if vga_sog == "1":
            values["analogue"] = analogue_label("rgb_pvm")
        elif composite_sync == "1":
            values["analogue"] = analogue_label("rgb_consumer")
        else:
            values["analogue"] = analogue_label("vga")
    else:
        values["analogue"] = analogue_label("rgb_consumer")

    logo = settings.get("logo", "1").strip()
    values["logo"] = enabled_disabled_label(logo != "0")

    font_value = settings.get("font", "").strip()
    if font_value.startswith("font/"):
        values["font"] = font_value.split("/", 1)[1].strip()
    else:
        values["font"] = default_font_label()

    return values


def build_easy_mode_settings(easy_values):
    settings = {}

    hdmi_mode = hdmi_mode_key(easy_values.get("hdmi_mode", ""))
    settings["direct_video"] = "1" if hdmi_mode == "direct_video" else "0"

    resolution = easy_values.get("resolution", "").strip()
    if resolution in RESOLUTION_REVERSE_MAP:
        settings["video_mode"] = RESOLUTION_REVERSE_MAP[resolution]

    scaling = scaling_key(easy_values.get("scaling", ""))
    scaling_reverse_map = {
        "disabled": "0",
        "low_latency": "1",
        "exact_refresh": "2",
    }
    settings["vsync_adjust"] = scaling_reverse_map.get(scaling, "1")

    audio = hdmi_audio_key(easy_values.get("hdmi_audio", ""))
    settings["dvi_mode"] = "1" if audio == "disabled_dvi" else "0"

    hdr = enabled_disabled_key(easy_values.get("hdr", ""))
    settings["hdr"] = "1" if hdr == "enabled" else "0"

    limited = hdmi_range_key(easy_values.get("hdmi_limited", ""))
    settings["hdmi_limited"] = "1" if limited == "limited" else "0"

    analogue = analogue_key(easy_values.get("analogue", ""))

    if analogue == "rgb_consumer":
        settings["vga_mode"] = "rgb"
        settings["composite_sync"] = "1"
        settings["vga_sog"] = "0"
    elif analogue == "rgb_pvm":
        settings["vga_mode"] = "rgb"
        settings["composite_sync"] = "0"
        settings["vga_sog"] = "1"
    elif analogue == "component":
        settings["vga_mode"] = "ypbpr"
        settings["composite_sync"] = "0"
        settings["vga_sog"] = "0"
    elif analogue == "svideo":
        settings["vga_mode"] = "svideo"
        settings["composite_sync"] = "0"
        settings["vga_sog"] = "0"
    elif analogue == "vga":
        settings["vga_mode"] = "rgb"
        settings["composite_sync"] = "0"
        settings["vga_sog"] = "0"

    logo = enabled_disabled_key(easy_values.get("logo", ""))
    settings["logo"] = "1" if logo == "enabled" else "0"

    font = easy_values.get("font", "").strip()
    if font and font != default_font_label() and font != "Default":
        settings["font"] = f"font/{font}"
    else:
        settings["font_commented"] = "font/myfont.pf"

    return settings


def update_mister_ini_text(ini_text, updated_settings):
    lines = ini_text.splitlines()
    new_lines = []

    in_mister_section = False
    replaced_keys = set()
    found_mister_section = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[") and stripped.endswith("]"):
            section_name = stripped[1:-1].strip()

            if in_mister_section and section_name != "MiSTer":
                for key, value in updated_settings.items():
                    if key not in replaced_keys:
                        if key == "font_commented":
                            new_lines.append(DEFAULT_FONT_LINE)
                        else:
                            new_lines.append(f"{key}={value}")

            in_mister_section = section_name == "MiSTer"
            if in_mister_section:
                found_mister_section = True

            new_lines.append(line)
            continue

        if in_mister_section:
            clean = stripped.lstrip(";").strip()

            if "=" in clean:
                key = clean.split("=", 1)[0].strip()

                if key == "font":
                    if "font" in updated_settings:
                        new_lines.append(f"font={updated_settings['font']}")
                        replaced_keys.add("font")
                        replaced_keys.add("font_commented")
                        continue
                    if "font_commented" in updated_settings:
                        new_lines.append(DEFAULT_FONT_LINE)
                        replaced_keys.add("font")
                        replaced_keys.add("font_commented")
                        continue

                if key in updated_settings and key not in ("font_commented",):
                    new_lines.append(f"{key}={updated_settings[key]}")
                    replaced_keys.add(key)
                    continue

        new_lines.append(line)

    if not found_mister_section:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("[MiSTer]")
        for key, value in updated_settings.items():
            if key == "font_commented":
                new_lines.append(DEFAULT_FONT_LINE)
            else:
                new_lines.append(f"{key}={value}")
    elif in_mister_section:
        for key, value in updated_settings.items():
            if key not in replaced_keys:
                if key == "font_commented":
                    new_lines.append(DEFAULT_FONT_LINE)
                else:
                    new_lines.append(f"{key}={value}")

    return "\n".join(new_lines) + "\n"