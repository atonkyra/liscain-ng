import zmq
import argparse


parser = argparse.ArgumentParser(description='liscain-opt82-hook')
parser.add_argument('-M', '--upstream-switch-mac', required=True, help='upstream switch mac', default=None)
parser.add_argument('-P', '--upstream-port-info', required=True, help='upstream switch port', default=None)
parser.add_argument('-m', '--downstream-switch-mac', required=True, help='downstream switch mac', default=None)
parser.add_argument('-z', '--zmq-socket', required=True, help='zmq-socket', default=None)
args = parser.parse_args()

c = zmq.Context()
s = c.socket(zmq.PUSH)
s.connect(args.zmq_socket)
s.send_json(
    {
        'upstream_switch_mac': args.upstream_switch_mac,
        'upstream_port_info': args.upstream_port_info,
        'downstream_switch_mac': args.downstream_switch_mac
    }
)
