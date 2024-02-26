import uuid
import threading


class TempStorage:
    def __init__(self):
        self._data = {}
        self._data_lock = threading.Lock()

    def store(self, data):
        with self._data_lock:
            k = str(uuid.uuid4())
            self._data[k] = data
            return k

    def get(self, k):
        with self._data_lock:
            if k in self._data:
                v = self._data[k]
                return v
            return None
