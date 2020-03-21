from devices.device import Device
import tasks
import typing
import threading


class CommandQueue(threading.Thread):
    def __init__(self, device: Device):
        super().__init__()
        self._device: Device = device
        self._command_queue: typing.List[tasks.DeviceTask] = list()
        self._command_queue_lock = threading.Lock()
        self._stop_event = threading.Event()

    def enqueue_task(self, task: tasks.DeviceTask):
        with self._command_queue_lock:
            for queued_task in self._command_queue:
                if task.unique:
                    if task.__class__ == queued_task.__class__:
                        raise KeyError('task already exists, will not enqueue')
            task.validate()
            self._command_queue.append(task)
        if not self.is_alive():
            self.start()

    def get_queue_list(self):
        out = []
        with self._command_queue_lock:
            for item in self._command_queue:
                out.append(item.__class__)
        return out

    def length(self):
        return len(self._command_queue)

    def stop(self):
        self._stop_event.set()
        if self.is_alive():
            self.join()

    def run(self):
        while not self._stop_event.is_set():
            task: typing.Optional[tasks.DeviceTask] = None
            with self._command_queue_lock:
                if len(self._command_queue) > 0:
                    task = self._command_queue[0]
            if task is not None:
                task.run()
                task.post()
                with self._command_queue_lock:
                    del self._command_queue[0]
            else:
                self._stop_event.wait(1)
