from lib.switchstate import SwitchState
from tasks.devicetask import DeviceTask
from devices.device import Device


class DeviceInitializationTask(DeviceTask):
    def __init__(self, device, **kwargs):
        super().__init__(device, **kwargs)
        self._logger = self.get_logger('deviceinit')

    def validate(self):
        if self._device.state not in [SwitchState.NEW, SwitchState.INIT, SwitchState.INIT_FAILED, SwitchState.READY, SwitchState.CONFIGURE_FAILED]:
            raise KeyError('switch not in correct state for initialization')

    def run(self):
        self._logger.info('start initialization')
        self._device.change_state(SwitchState.INIT)
        if not self._device.initial_setup():
            self._device.change_state(SwitchState.INIT_FAILED)
            self._logger.info('initialization failed')
            return
        self._device.change_state(SwitchState.READY)
        self._logger.info('initialization complete')
