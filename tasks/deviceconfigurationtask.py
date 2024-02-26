import tasks.devicetask
from lib.switchstate import SwitchState
from lib.temp_storage import TempStorage
from devices.device import Device


class DeviceConfigurationTask(tasks.devicetask.DeviceTask):
    def __init__(self, device, **kwargs):
        super().__init__(device, **kwargs)
        self._logger = self.get_logger('deviceconf')

    def validate(self) -> bool:
        if self._device.state not in [SwitchState.READY, SwitchState.CONFIGURE_FAILED]:
            raise KeyError('switch not in correct state for configuration')

    def run(self):
        self._logger.info('begin configuration')
        if not self._device.change_identity(self._args.get('identity')):
            self._device.change_state(SwitchState.CONFIGURE_FAILED)
            self._logger.info('identity setup failed')
            return
        if not self._device.configure(self._args.get('configuration'), self._args.get('temp_storage')):
            self._device.change_state(SwitchState.CONFIGURE_FAILED)
            self._logger.info('configuration failed')
            return
        self._device.change_state(SwitchState.CONFIGURED)
        self._logger.info('configuration complete')
