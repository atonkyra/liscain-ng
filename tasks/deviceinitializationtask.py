from lib.switchstate import SwitchState
from tasks.devicetask import DeviceTask
from devices.device import Device


class DeviceInitializationTask(DeviceTask):

    def validate(self):
        if self._device.state not in [SwitchState.NEW, SwitchState.INIT, SwitchState.INIT_FAILED, SwitchState.READY]:
            raise KeyError('switch not in correct state for initialization')

    def run(self):
        self._device.change_state(SwitchState.INIT)
        if not self._device.initial_setup():
            self._device.change_state(SwitchState.INIT_FAILED)
            return
        self._device.change_state(SwitchState.READY)
