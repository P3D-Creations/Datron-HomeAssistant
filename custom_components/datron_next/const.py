"""Constants for the Datron NEXT integration."""

DOMAIN = "datron_next"

CONF_HOST = "host"
CONF_TOKEN = "token"
CONF_PORT = "port"

DEFAULT_PORT = 80
API_VERSION = "2"

# Polling intervals in seconds
SCAN_INTERVAL_FAST = 2  # Machine status, job progress, axes, sensors, notifications
SCAN_INTERVAL_MEDIUM = 5  # Tools, program info
SCAN_INTERVAL_SLOW = 3600  # Machine info, software version, licenses

# Coordinator data keys
COORD_FAST = "fast"
COORD_MEDIUM = "medium"
COORD_SLOW = "slow"

# Machine execution states
MACHINE_STATE_INIT = "Init"
MACHINE_STATE_PREPARING = "Preparing"
MACHINE_STATE_IDLE = "Idle"
MACHINE_STATE_RUNNING = "Running"
MACHINE_STATE_PAUSE = "Pause"
MACHINE_STATE_MANUAL = "Manual"
MACHINE_STATE_ABORTING = "Aborting"
MACHINE_STATE_ABORTED = "Aborted"
MACHINE_STATE_TRANSIENT = "Transient"
MACHINE_STATE_WAITING = "WaitingForUserInput"

# Notification types
NOTIFICATION_TYPE_ERROR = "Error"
NOTIFICATION_TYPE_WARNING = "Warning"
NOTIFICATION_TYPE_INFO = "Info"
NOTIFICATION_TYPE_TEMPORARY = "Temporary"
