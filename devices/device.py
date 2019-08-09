import lib.db
import lib.switchstate
from sqlalchemy import Column, Integer, String, orm, Enum
import logging


class Device(lib.db.base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    identifier = Column(String, nullable=False, default=None)
    address = Column(String, nullable=False, default=None)
    state = Column(Enum(lib.switchstate.SwitchState), nullable=False, default=None)
    device_type = Column(String, nullable=False, default='UNKNOWN')
    mac_address = Column(String, nullable=False, default='UNKNOWN')

    def __init__(self):
        super().__init__()
        self._logger = None

    def initialize(self, identifier, address):
        self._logger = logging.getLogger('[{}]'.format(identifier))
        self._logger.info('new switch')
        self.identifier = identifier
        self.address = address
        self.state = lib.switchstate.SwitchState.INIT
        self.device_type = 'UNKNOWN'
        self.mac_address = 'UNKNOWN'

    @orm.reconstructor
    def reconstruct(self):
        self._logger = logging.getLogger('[{}]'.format(self.identifier))
        self._logger.info('load switch')

    def change_state(self, state):
        self._logger.info('change state %s -> %s', self.state, state)
        self.state = state
        self.save()

    def save(self):
        with lib.db.sql_ses() as ses:
            ses.merge(self)
            ses.commit()
