import tftpy
import logging
import ipaddress
import threading
import time
import lib.db
import sqlalchemy.orm
from sqlalchemy import and_
from devices import remap_to_subclass
from devices.device import Device
from devices.ciscoswitch import CiscoSwitch
from io import StringIO
from lib.config import config
from lib.switchstate import SwitchState
import zmq


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)-8s %(name)-12s %(message)s'
)
logger = logging.getLogger('lis-cain')
logger.setLevel(logging.INFO)
logging.getLogger('tftpy.TftpServer').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpPacketTypes').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpStates').setLevel(logging.CRITICAL)


def serve_file(name, **kwargs):
    remote_address = kwargs['raddress']
    remote_id = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))
    if name in ['network-confg']:
        device = None
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(CiscoSwitch).filter(
                    and_(
                        CiscoSwitch.identifier == remote_id,
                        CiscoSwitch.state != SwitchState.CONFIGURED
                    )
                ).one()
            except sqlalchemy.orm.exc.NoResultFound:
                device = CiscoSwitch()
                device.initialize(identifier=remote_id, address=remote_address)
                ses.add(device)
                ses.commit()
                ses.refresh(device)
        if device.state in [SwitchState.INIT, SwitchState.INIT_IN_PROGRESS, SwitchState.INIT_TIMEOUT, SwitchState.READY]:
            if device.state != SwitchState.INIT_IN_PROGRESS:
                device.change_state(SwitchState.INIT_IN_PROGRESS)
                threading.Thread(target=device.pull_init_info, daemon=True).start()
            return device.emit_base_config()
        else:
            logger.info('%s requests config, but is in state %s', remote_id, device.state)
        return StringIO()
    else:
        logger.debug('%s requested %s, ignoring', remote_id, name)
    return StringIO()


def tftp_server():
    srv = tftpy.TftpServer(tftproot=None, dyn_file_func=serve_file)
    srv.listen()


def handle_msg(message):
    cmd = message.get('cmd', None)
    if cmd == 'list':
        ret = []
        with lib.db.sql_ses() as ses:
            devices = ses.query(Device).all()
            for device in devices:
                ret.append(device.as_dict())
        return ret

    elif cmd == 'status':
        device_id = message.get('id', None)
        if device_id is None:
            return {'error': 'missing device id'}
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(Device).filter(Device.id == device_id).one()
                return device.as_dict()
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'device not found'}

    elif cmd == 'adopt':
        device_id = message.get('id', None)
        switch_config = message.get('config', None)
        identity = message.get('identity', None)
        if device_id is None:
            return {'error': 'missing device id'}
        if config is None:
            return {'error': 'missing config'}
        if identity is None:
            return {'error': 'missing identity'}
        device = None
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(Device).filter(Device.id == device_id).one()
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'device not found'}
        if device.state not in [SwitchState.CONFIGURE_FAILED, SwitchState.READY]:
            return {'error': 'switch not in READY or CONFIGURE_FAILED state'}
        remap_to_subclass(device)
        device.change_state(SwitchState.CONFIGURING)
        if not device.change_identity(identity):
            device.change_state(SwitchState.CONFIGURE_FAILED)
            return {'error': 'failed to change identity, failing configuration step'}
        threading.Thread(target=device.configure, daemon=True, args=(switch_config,)).start()
        return device.as_dict()
    return {'error': 'unknown command'}


def main():
    lib.db.initialize(config.get('liscain', 'database'))
    tftp_task = threading.Thread(target=tftp_server, daemon=True)
    tftp_task.start()
    zmq_context = zmq.Context()
    zmq_sock = zmq_context.socket(zmq.REP)
    zmq_sock.bind('tcp://127.0.0.1:1337')
    while True:
        msg = zmq_sock.recv_json()
        zmq_sock.send_json(handle_msg(msg))


if __name__ == '__main__':
    main()

