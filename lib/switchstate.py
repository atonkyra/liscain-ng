from enum import Enum


class SwitchState(Enum):
    CONFIGURE_FAILED = -2
    INIT_TIMEOUT = -1
    INIT = 0
    INIT_IN_PROGRESS = 1
    READY = 2
    CONFIGURING = 3
    CONFIGURED = 4

    def __str__(self):
        return self.name
