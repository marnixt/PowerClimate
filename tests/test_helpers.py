from custom_components.powerclimate.helpers import get_strings
from custom_components.powerclimate.const import DOMAIN


def test_get_strings_falls_back_to_english(hass):
    strings = get_strings(hass, language="zz")
    assert strings
    assert strings.get("unavailable") == "unavailable"
    assert strings.get("label_room") == "Room"


def test_get_strings_uses_config_language(hass):
    hass.config.language = "en"
    strings = get_strings(hass)
    assert strings.get("label_power") == "Power"
*** End File