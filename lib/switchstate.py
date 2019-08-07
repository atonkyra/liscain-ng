from enum import Enum


class SwitchState(Enum):
    INIT = 0
    READY = 1

    INIT_TIMEOUT = -1
