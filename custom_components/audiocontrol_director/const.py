"""Constants for AudioControl Director."""

from datetime import timedelta

DOMAIN = "audiocontrol_director"
MANUFACTURER = "AudioControl"

CONF_MAC = "mac"
# Entries made by the old integration kept their user-chosen ID here.
CONF_LEGACY_UNIQUE_ID = "unique_id"
CONF_SOURCE_NAMES = "source_names"

UPDATE_INTERVAL = timedelta(seconds=5)
# Loudness needs one query per zone, so it is read less often.
LOUDNESS_INTERVAL = timedelta(seconds=60)
