"""Constants for AudioControl Director."""

from datetime import timedelta

DOMAIN = "audiocontrol_director"
MANUFACTURER = "AudioControl"

CONF_MAC = "mac"
# Entries made by the old integration kept their user-chosen ID here.
CONF_LEGACY_UNIQUE_ID = "unique_id"
CONF_SOURCE_NAMES = "source_names"

UPDATE_INTERVAL = timedelta(seconds=5)
# Failed polls in a row that keep the last status before players go
# unavailable; a single dropped or garbled reply shouldn't make them flicker.
MAX_MISSED_POLLS = 3
# Zone activity (Signal Sense) from the web page's /json/operation.json; the poll
# interval is an option (seconds).
CONF_SIGNAL_INTERVAL = "signal_interval"
DEFAULT_SIGNAL_INTERVAL = 10
MIN_SIGNAL_INTERVAL = 2
MAX_SIGNAL_INTERVAL = 300
# Loudness needs one query per zone, so it is read less often.
LOUDNESS_INTERVAL = timedelta(seconds=60)
