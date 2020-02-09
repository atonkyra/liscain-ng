from lib.db import sql_ses, base
from sqlalchemy import Column, Integer, String, orm, Enum, and_, not_
import sqlalchemy.orm
import logging
from lib.config import config
import zmq
import time
from devices import remap_to_subclass
from devices.device import Device
from lib.switchstate import SwitchState
import threading


class Option82Info(base):
    __tablename__ = 'option82_infos'
    id = Column(Integer, primary_key=True)
    upstream_switch_mac = Column(String, nullable=False, default=None)
    upstream_port_info = Column(String, nullable=False, default=None)
    downstream_switch_mac = Column(String, nullable=True, default=None)
    downstream_switch_name = Column(String, nullable=True, default=None)

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
        return ret


class Option82:
    def __init__(self):
        self._logger = logging.getLogger('option82')

    def update_info(self, upstream_switch_mac, upstream_port_info, downstream_switch_mac):
        with sql_ses() as ses:
            try:
                info = ses.query(Option82Info).filter(
                    and_(
                        Option82Info.upstream_switch_mac == upstream_switch_mac,
                        Option82Info.upstream_port_info == upstream_port_info
                    )
                ).one()

                old_mac_infos = ses.query(Option82Info).filter(
                    and_(
                        Option82Info.downstream_switch_mac == downstream_switch_mac,
                        Option82Info.id != info.id
                    )
                ).all()
                cleared_entries = 0
                for old_mac_info in old_mac_infos:
                    old_mac_info.downstream_switch_mac = None
                    ses.add(old_mac_info)
                    cleared_entries += 1
                if len(old_mac_infos) > 0:
                    ses.commit()
                    self._logger.info('cleared %s entries for %s', cleared_entries, downstream_switch_mac)

                if info.downstream_switch_mac != downstream_switch_mac:
                    old_downstream_mac = info.downstream_switch_mac
                    info.downstream_switch_mac = downstream_switch_mac
                    ses.add(info)
                    ses.commit()
                    self._logger.info(
                        'updated downstream switch mac for %s @ %s (%s -> %s)',
                        info.upstream_switch_mac,
                        info.upstream_port_info,
                        old_downstream_mac,
                        info.downstream_switch_mac
                    )
            except sqlalchemy.orm.exc.NoResultFound:
                self._logger.info('no option82 info found for %s @ %s', upstream_switch_mac, upstream_port_info)

    def set_association(self, upstream_switch_mac, upstream_port_info, downstream_switch_name):
        upstream_port_info = upstream_port_info.lower()
        upstream_switch_mac = upstream_switch_mac.lower()
        with sql_ses() as ses:
            info = None
            try:
                info = ses.query(Option82Info).filter(
                    and_(
                        Option82Info.upstream_switch_mac == upstream_switch_mac,
                        Option82Info.upstream_port_info == upstream_port_info
                    )
                ).one()
                info.downstream_switch_name = downstream_switch_name
                ses.add(info)
                ses.commit()
            except sqlalchemy.orm.exc.NoResultFound:
                info = Option82Info()
                info.upstream_switch_mac = upstream_switch_mac
                info.upstream_port_info = upstream_port_info
                info.downstream_switch_name = downstream_switch_name
                ses.add(info)
                ses.commit()
            finally:
                self._logger.info(
                    'option82 association set to %s for %s @ %s',
                    downstream_switch_name,
                    upstream_switch_mac,
                    upstream_port_info
                )
                return info.as_dict()

    def _handle_message(self, message):
        upstream_port_info = message.get('upstream_port_info', None).lower()
        upstream_switch_mac = message.get('upstream_switch_mac', None).lower()
        downstream_switch_mac = message.get('downstream_switch_mac', None).lower()
        if upstream_port_info is None or upstream_switch_mac is None or downstream_switch_mac is None:
            self._logger.error(
                'incomplete option82 data, ignoring (usm=%s, usp=%s, dsm=%s)',
                upstream_switch_mac,
                upstream_port_info,
                downstream_switch_mac
            )
            return
        self.update_info(upstream_switch_mac, upstream_port_info, downstream_switch_mac)

    def _check_autoadopt_switches(self):
        ready_devices = None
        associations = None
        with sql_ses() as ses:
            ready_devices = ses.query(Device).filter(Device.state == SwitchState.READY).all()
            associations = ses.query(Option82Info).all()
        assoc_map = {}
        for assoc in associations:
            if assoc.downstream_switch_mac is not None:
                assoc_map[assoc.downstream_switch_mac] = assoc
        for ready_device in ready_devices:
            if ready_device.mac_address in assoc_map:
                autoconf_path = config.get('liscain', 'autoconf_path')
                whitelisted_prefixes = config.get('liscain', 'autoconf_version_whitelist_prefix')
                autoconf_ok = False
                if whitelisted_prefixes is None:
                    autoconf_ok = True
                else:
                    whitelisted_prefixes = whitelisted_prefixes.split(',')
                    for whitelisted_prefix in whitelisted_prefixes:
                        if ready_device.version.startswith(whitelisted_prefix):
                            autoconf_ok = True
                            break
                switch_name = assoc_map[ready_device.mac_address].downstream_switch_name
                if not autoconf_ok:
                    self._logger.info('%s (%s @ %s) does not meet autoconf criteria (version)', switch_name, ready_device.identifier, ready_device.address)
                    continue
                config_path = '{}/{}.cfg'.format(autoconf_path, switch_name)

                self._logger.info('trying autoadopt for %s', switch_name)

                switch_config = None
                try:
                    with open(config_path) as fp:
                        switch_config = fp.read()
                except FileNotFoundError:
                    self._logger.error('failed to open %s for switch autoconfiguration', config_path)
                    continue
                remap_to_subclass(ready_device)
                ready_device.change_state(SwitchState.CONFIGURING)
                if not ready_device.change_identity(switch_name):
                    ready_device.change_state(SwitchState.CONFIGURE_FAILED)
                    self._logger.error('failed to change identity for %s, failing configuration step', switch_name)
                    continue
                time.sleep(1)
                threading.Thread(target=ready_device.configure, daemon=True, args=(switch_config,)).start()

    def autoadopt(self, zmq_context):
        zmq_socket = zmq_context.socket(zmq.PULL)
        zmq_socket.bind(config.get('liscain', 'opt82_zmq_listener'))
        i = 0
        while True:
            msg_received = False
            try:
                msg = zmq_socket.recv_json(flags=zmq.NOBLOCK)
                self._handle_message(msg)
                msg_received = True
            except zmq.Again:
                pass
            if i % 10 == 0:
                self._check_autoadopt_switches()
            if not msg_received:
                time.sleep(0.1)
            i += 1
