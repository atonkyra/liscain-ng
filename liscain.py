import tempfile
import tftpy
import logging
import ipaddress
import threading
import lib.db
import sqlalchemy.orm
import tasks
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from sqlalchemy import and_
from devices import remap_to_subclass
from devices.device import Device
from devices.ciscoios import CiscoIOS
from io import StringIO
from lib.config import config
from lib.switchstate import SwitchState
from lib.option82 import Option82
from lib.cdp_adopter import CDPAdopter
from lib.commander import Commander
from lib.temp_storage import TempStorage
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

temp_storage: lib.temp_storage.TempStorage = TempStorage()

cdp_adopter: lib.cdp_adopter.CDPAdopter = lib.cdp_adopter.CDPAdopter(commander, temp_storage)
option82_controller: lib.option82.Option82 = lib.option82.Option82(commander, temp_storage)


def serve_file(name: str, **kwargs) -> StringIO:
    global commander
    global cdp_adopter
    global option82_controller
    global temp_storage

    remote_address: str = kwargs['raddress']
    remote_id: str = 'lc-{:02x}'.format(int(ipaddress.ip_address(remote_address)))

    filepath = Path(name)

    if len(filepath.parts) == 2 and filepath.parts[0] == 'adopt':
        storage_data = temp_storage.get(filepath.name)
        if storage_data is not None:
            return StringIO(storage_data)
    elif name in ['network-confg', 'switch-confg']:
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
                autoconf_mode = None
                try:
                    autoconf_mode = config.get('liscain', 'autoconf_mode')
                except Exception:
                    logger.error("init/%s: failed to get autoconf_mode (is autoconf_mode set in config?)", remote_id)
                if autoconf_mode == 'cdp':
                    task.hook(SwitchState.READY, cdp_adopter.autoadopt)
                elif autoconf_mode == 'opt82':
                    task.hook(SwitchState.READY, option82_controller.autoadopt)
            commander.enqueue(device, task)
        except KeyError as e:
            logger.error('init/%s: %s', remote_id, e)
        return device.emit_base_config()
    else:
        logger.debug('%s requested %s, ignoring', remote_id, name)
    return StringIO()


def tftp_server():
    with tempfile.TemporaryDirectory() as td:
        srv = tftpy.TftpServer(tftproot=td, dyn_file_func=serve_file)
        srv.listen()


def handle_msg(message):
    global option82_controller
    global cdp_adopter
    global temp_storage

    cmd = message.get('cmd', None)
    if cmd == 'list':
        ret = []
        with lib.db.sql_ses() as ses:
            devices = ses.query(Device).all()
            for device in devices:
                queued_commands = len(commander.get_queue_list(device))
                device_dict = device.as_dict()
                device_dict['cqueue'] = queued_commands
                ret.append(device_dict)
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
                queued_commands = commander.get_queue_list(device)
                device_dict = device.as_dict()
                device_dict['cqueue'] = len(queued_commands)
                device_dict['cqueue_items'] = queued_commands
                return device_dict
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
        try:
            commander.enqueue(
                device,
                tasks.DeviceConfigurationTask(device, identity=identity, configuration=switch_config, temp_storage=temp_storage)
            )
            return {'info': 'ok'}
        except BaseException as e:
            return {'error': str(e)}

    elif cmd == 'reinit':
        device_id = message.get('id', None)
        if device_id is None:
            return {'error': 'missing device id'}
        device = None
        with lib.db.sql_ses() as ses:
            try:
                device = ses.query(Device).filter(Device.id == device_id).one()
            except sqlalchemy.orm.exc.NoResultFound:
                return {'error': 'device not found'}
        remap_to_subclass(device)
        try:
            task = tasks.DeviceInitializationTask(device)
            if config.get('liscain', 'autoconf_enabled') == 'yes':
                if config.get('liscain', 'autoconf_mode') == 'cdp':
                    task.hook(SwitchState.READY, cdp_adopter.autoadopt)
                if config.get('liscain', 'autoconf_mode') == 'opt82':
                    task.hook(SwitchState.READY, option82_controller.autoadopt)
            commander.enqueue(
                device,
                task
            )
            return {'info': 'ok'}
        except BaseException as e:
            return {'error': str(e)}

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


class LiscainHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global temp_storage

        filepath = Path(self.path.strip('/'))
        if len(filepath.parts) == 2 and filepath.parts[0] == 'adopt':
            storage_data = temp_storage.get(filepath.name)
            if storage_data is not None:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(storage_data.encode('utf-8'))
                return

        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'')


def http_server_startup():
    server_address = ('', config.getint("liscain", "http_port"))
    httpd = ThreadingHTTPServer(server_address, LiscainHTTPRequestHandler)
    httpd.serve_forever()


def main():
    global option82_controller

    lib.db.initialize(config.get('liscain', 'database'))
    tftp_task: threading.Thread = threading.Thread(target=tftp_server, daemon=True)
    tftp_task.start()

    http_task = None
    if config.getboolean("liscain", "serve_http", fallback=False):
        http_task: threading.Thread = threading.Thread(target=http_server_startup, daemon=True)
        http_task.start()

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

