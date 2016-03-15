import getopt
import socket
import struct
import sys

from Queue import Queue
from daemonize import Daemonize
from pysnmp.hlapi import *

import ioxclient
import modbus

pid = "/tmp/ioxclient.pid"
port = 65535
secret = 'S#cr#t'
ioxregd_server = 'm2m.iox.com.pl'
client = ""
m = ""
q = {"one":Queue(), "two":Queue()}
slaves = {}
name = ""
region = ""
gps = False
foreground = False

def get_snmp():
    name = "phony-rtr"
    region = "phony region"
    gw = get_default_gateway()
    errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                   CommunityData('i0xCl!#nt'),
                   UdpTransportTarget((gw, 161)),
                   ContextData(),
                   ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')),
                   ObjectType(ObjectIdentity('1.3.6.1.2.1.1.6.0')))
    )
    if errorIndication:
        print(errorIndication)
    elif errorStatus:
        print('get_snmp() %s at %s' % (errorStatus.prettyPrint(), errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
    else:
        name = str(varBinds[0][1]).split(".")[0]
        region = str(varBinds[1][1])
        return [name, region]

def get_default_gateway():
    with open("/proc/net/route") as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))


def main():
    global name, region
    if not name or not region:
        name, region = get_snmp()
    client = ioxclient.Ioxclient(ioxregd_server, port, secret,slaves,q,name,region,gps)
    client.daemon = True
    client.loop()
    m = modbus.Modbus(5,q,ioxclient.log,slaves)
    m.daemon = True
    m.loop()
    client.attach(m)
    m.attach(client)
    try:
        while client.is_alive() or m.is_alive():
            client.join(timeout=1.0)
            m.join(timeout=1.0)
    except (KeyboardInterrupt,SystemExit):
        ioxclient.log.info("KILLED BY CTRL+C")
        sys.exit(2)

try:
    opts, args = getopt.getopt(sys.argv[1:],"hfA:B:C:D:n:r:g",["foreground","help","modbus1:","modbus2:","modbus3:","modbus4","name:","region:","gps"])
except getopt.GetoptError:
    print 'server.py -h'
    sys.exit(2)

for opt, arg in opts:
  if opt == '-h':
     print 'server.py -f -T -H -V -R'
     sys.exit()
  elif opt in ("-f", "--foreground"):
      foreground = True
  elif opt in ("-A", "--modbus1"):
      slaves["1"] = arg
  elif opt in ("-B", "--modbus2"):
      slaves["2"] = arg
  elif opt in ("-C", "--modbus3"):
      slaves["3"] = arg
  elif opt in ("-D", "--modbus4"):
      slaves["4"] = arg
  elif opt in ("-n", "--name"):
      name = arg
  elif opt in ("-g", "--gps"):
      gps = True
  elif opt in ("-r", "--region"):
      region = arg
#main()

daemon = Daemonize(app="ioxclient", pid=pid, action=main, chdir="./", logger=ioxclient.log, keep_fds=[ioxclient.fh.stream.fileno()], foreground=foreground)
daemon.start()
