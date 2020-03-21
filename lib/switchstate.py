from enum import Enum


class SwitchState(Enum):
    CONFIGURE_FAILED = -2
    INIT_FAILED = -1
    NEW = 0
    INIT = 1
    READY = 2
    CONFIGURED = 3

    def __str__(self):
        return self.name
