import getopt
import sys

from Queue import Queue
from daemonize import Daemonize

import ioxclient
import modbus

pid = "/tmp/ioxclient.pid"
port = 65535
secret = 'S#cr#t'
ioxregd_server = '127.0.0.1'
client = ""
m = ""
q = {"one":Queue(), "two":Queue()}
slaves = {}
name = ""
region = ""
foreground = False

def main():
    client = ioxclient.Ioxclient(ioxregd_server, port, secret,slaves,q,name,region)
    client.daemon = True
    client.loop()
    m = modbus.Modbus(5,q,ioxclient.log,slaves)
    m.daemon = True
    m.loop()
    client.attach(m)
    try:
        while client.is_alive() or m.is_alive():
            client.join(timeout=1.0)
            m.join(timeout=1.0)
    except (KeyboardInterrupt,SystemExit):
        ioxclient.log.info("KILLED BY CTRL+C")
        sys.exit(2)

#signal.signal(signal.SIGINT, signal_handler)

try:
    opts, args = getopt.getopt(sys.argv[1:],"hfA:B:C:D:n:r:",["foreground","help","modbus1:","modbus2:","modbus3:","modbus4","name:","region:"])
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
  elif opt in ("-r", "--region"):
      region = arg
main()

daemon = Daemonize(app="ioxclient", pid=pid, action=main, chdir="./", logger=ioxclient.log, keep_fds=[ioxclient.fh.stream.fileno()], foreground=foreground)
daemon.start()