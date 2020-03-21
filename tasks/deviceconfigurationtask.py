import tasks.devicetask
from lib.switchstate import SwitchState
from devices.device import Device


class DeviceConfigurationTask(tasks.devicetask.DeviceTask):
    def validate(self) -> bool:
        if self._device.state not in [SwitchState.READY]:
            return False
        return True

    def run(self):
        if not self._device.change_identity(self._args.get('identity')):
            self._device.change_state(SwitchState.CONFIGURE_FAILED)
            return
        if not self._device.configure(self._args.get('configuration')):
            self._device.change_state(SwitchState.CONFIGURE_FAILED)
        self._device.change_state(SwitchState.CONFIGURED)
