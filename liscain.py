import tftpy
import logging
import ipaddress
import threading
import lib.db
import sqlalchemy.orm
import tasks
from sqlalchemy import and_
from devices import remap_to_subclass
from devices.device import Device
from devices.ciscoios import CiscoIOS
from io import StringIO
from lib.config import config
from lib.switchstate import SwitchState
from lib.option82 import Option82
from lib.commander import Commander
import zmq


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)-8s %(name)-16s %(message)s'
)
logger = logging.getLogger('lis-cain')
logger.setLevel(logging.INFO)
logging.getLogger('tftpy.TftpServer').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpPacketTypes').setLevel(logging.CRITICAL)
logging.getLogger('tftpy.TftpStates').setLevel(logging.CRITICAL)


commander: Commander = Commander()
commander.start()
option82_controller: lib.option82.Option82 = lib.option82.Option82(commander)


def serve_file(name: str, **kwargs) -> StringIO:
    global commander
    global option82_controller

    remote_address: str = kwargs['raddress']
    remote_id: str = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))
    if name in ['network-confg']:
        device = None
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(CiscoIOS).filter(
                    and_(
                        CiscoIOS.identifier == remote_id,
                        CiscoIOS.state != SwitchState.CONFIGURED
                    )
                ).one()
            except sqlalchemy.orm.exc.NoResultFound:
                device = CiscoIOS()
                device.initialize(identifier=remote_id, address=remote_address)
                ses.add(device)
                ses.commit()
                ses.refresh(device)
        try:
            task = tasks.DeviceInitializationTask(device)
            if config.get('liscain', 'autoconf_enabled') == 'yes':
                task.hook(SwitchState.READY, option82_controller.autoadopt)
            commander.enqueue(device, task)
        except KeyError as e:
            logger.error('init/%s: %s', remote_id, e)
        return device.emit_base_config()
    else:
        logger.debug('%s requested %s, ignoring', remote_id, name)
    return StringIO()


def tftp_server():
    srv = tftpy.TftpServer(tftproot='c:/tmp', dyn_file_func=serve_file)
    srv.listen()


def handle_msg(message):
    global option82_controller

    cmd = message.get('cmd', None)
    if cmd == 'list':
        ret = []
        with lib.db.sql_ses() as ses:
            devices = ses.query(Device).all()
            for device in devices:
                ret.append(device.as_dict())
        return ret

    elif cmd == 'neighbor-info':
        device_id = message.get('id', None)
        if device_id is None:
            return {'error': 'missing device id'}
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(Device).filter(Device.id == device_id).one()
                remap_to_subclass(device)
                return {'info': device.neighbor_info()}
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'device not found'}

    elif cmd == 'delete':
        device_id = message.get('id', None)
        if device_id is None:
            return {'error': 'missing device id'}
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(Device).filter(Device.id == device_id).one()
                ses.delete(device)
                ses.commit()
                return {'info': 'device deleted'}
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'device not found'}

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
        remap_to_subclass(device)
        if not commander.enqueue(
            device,
            tasks.DeviceConfigurationTask(device, identity=identity, configuration=switch_config)
        ):
            return {'error': 'FIXME'}
        return device.as_dict()

    elif cmd == 'opt82-info':
        upstream_switch_mac = message.get('upstream_switch_mac', None)
        upstream_port_info = message.get('upstream_port_info', None)
        downstream_switch_name = message.get('downstream_switch_name', None)
        if upstream_switch_mac is None:
            return {'error': 'missing upstream switch mac'}
        if upstream_port_info is None:
            return {'error': 'missing upstream port info'}
        info = option82_controller.set_association(upstream_switch_mac, upstream_port_info, downstream_switch_name)
        return info

    elif cmd == 'opt82-list':
        opt82_items = []
        with lib.db.sql_ses() as ses:
            for option82_item in ses.query(lib.option82.Option82Info).all():
                opt82_items.append(option82_item.as_dict())
        return opt82_items

    elif cmd == 'opt82-delete':
        item_id = message.get('id', None)
        if item_id is None:
            return {'error': 'missing opt82 item id'}
        with lib.db.sql_ses() as ses:
            try:
                opt82_item = ses.query(lib.option82.Option82Info).filter(lib.option82.Option82Info.id == item_id).one()
                ses.delete(opt82_item)
                ses.commit()
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'option82 item not found'}
        return {'info': 'option82 info deleted'}

    return {'error': 'unknown command'}


def main():
    global option82_controller

    lib.db.initialize(config.get('liscain', 'database'))
    tftp_task: threading.Thread = threading.Thread(target=tftp_server, daemon=True)
    tftp_task.start()
    zmq_context: zmq.Context = zmq.Context(10)
    zmq_sock: zmq.socket = zmq_context.socket(zmq.REP)
    zmq_sock.bind(config.get('liscain', 'command_socket'))

    option82_controller_autoadopt: threading.Thread = threading.Thread(
        target=option82_controller.autoadopt_mapping_listener,
        args=(zmq_context,),
        daemon=True
    )
    option82_controller_autoadopt.start()

    while True:
        msg: dict = zmq_sock.recv_json()
        zmq_sock.send_json(handle_msg(msg))


if __name__ == '__main__':
    main()

