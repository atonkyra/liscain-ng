from devices.device import Device
import typing
from lib.commandqueue import CommandQueue
import threading
import tasks
import time


class Commander(threading.Thread):
    def __init__(self):
        super().__init__()
        self._command_queues: typing.Dict[int, CommandQueue] = dict()
        self._command_queue_lock = threading.Lock()
        self._stop_event = threading.Event()

    def enqueue(self, device: Device, task: tasks.DeviceTask):
        with self._command_queue_lock:
            if device.id not in self._command_queues:
                self._command_queues[device.id] = CommandQueue(device)
            if not self.is_alive():
                self.start()
            self._command_queues[device.id].enqueue_task(task)

    def get_queue_list(self, device):
        with self._command_queue_lock:
            if device.id not in self._command_queues:
                return []
            return self._command_queues[device.id].get_queue_list()

    def stop(self):
        self._stop_event.set()
        if self.is_alive():
            self.join()

    def run(self):
        while not self._stop_event.is_set():
            with self._command_queue_lock:
                delete_list = []
                for device_id, command_queue in self._command_queues.items():
                    if command_queue.length() == 0 or not command_queue.is_alive():
                        command_queue.stop()
                        delete_list.append(device_id)
                for device_id in delete_list:
                    del self._command_queues[device_id]
            self._stop_event.wait(60)


