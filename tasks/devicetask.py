from devices.device import Device
from lib.switchstate import SwitchState
import typing


class DeviceTask:
    def __init__(self, device, **kwargs):
        self._device: Device = device
        self.unique: bool = True
        self.complete: bool = False
        self._args: typing.Dict[str, str] = kwargs
        self._hooks: typing.Dict[SwitchState, typing.Any] = dict()

    def validate(self) -> bool:
        raise NotImplementedError("validate not implemented")

    def run(self):
        raise NotImplementedError("run not implemented")

    def post(self):
        if self._device.state in self._hooks:
            self._hooks[self._device.state](self._device)

    def hook(self, switchstate: SwitchState, callback):
        self._hooks[switchstate] = callback
