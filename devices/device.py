import lib.db
from lib.switchstate import SwitchState
from sqlalchemy import Column, Integer, String, orm, Enum
import logging
from enum import Enum as PyEnum


class Device(lib.db.base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    identifier = Column(String, nullable=False, default=None)
    address = Column(String, nullable=False, default=None)
    state = Column(Enum(SwitchState), nullable=False, default=None)
    device_type = Column(String, nullable=False, default='UNKNOWN')
    device_class = Column(String, nullable=False)
    mac_address = Column(String, nullable=False, default='UNKNOWN')
    version = Column(String, nullable=False, default='UNKNOWN')

    def __init__(self):
        super().__init__()
        self._logger = None

    def initialize(self, identifier, address):
        self._logger = logging.getLogger('[{}]'.format(identifier))
        self.identifier = identifier
        self.address = address
        self.state = lib.switchstate.SwitchState.NEW
        self.device_type = 'UNKNOWN'
        self.mac_address = 'UNKNOWN'
        self.version = 'UNKNOWN'
        self._logger.info('initialized switch information')

    @orm.reconstructor
    def reconstruct(self):
        self._logger = logging.getLogger('[{}]'.format(self.identifier))
        self._logger.debug('load switch from database')

    def neighbor_info(self):
        self._logger.error('called default neighbor info, this is not implemented')
        return 'unknown'

    def initial_setup(self) -> bool:
        raise NotImplementedError('initial setup not implemented')

    def change_state(self, state: SwitchState):
        self._logger.info('change state %s -> %s', self.state, state)
        self.state = state
        self.save()

    def change_identity(self, identity):
        self.identifier = identity
        self.save()
        self._logger.info('changed identity -> %s', self.identifier)
        self._logger = logging.getLogger('[{}]'.format(self.identifier))
        return True

    def configure(self, _config):
        self._logger.error('called default configure, no-op! setting device to CONFIGURE_FAILED')
        self.change_state(lib.switchstate.SwitchState.CONFIGURE_FAILED)

    def save(self):
        with lib.db.sql_ses() as ses:
            ses.merge(self)
            ses.commit()

    def as_dict(self):
        ret = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name)
            if isinstance(val, str):
                ret[col.name] = val
            elif isinstance(val, int):
                ret[col.name] = val
            elif isinstance(val, float):
                ret[col.name] = val
            elif isinstance(val, PyEnum):
                ret[col.name] = str(val)
        return ret

