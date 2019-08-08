from enum import Enum


class SwitchState(Enum):
    INIT_TIMEOUT = -1
    INIT = 0
    INIT_IN_PROGRESS = 1
    READY = 2
    CONFIGURING = 2
    CONFIGURED = 3
