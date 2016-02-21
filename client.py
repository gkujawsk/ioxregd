import getopt
import signal
import sys

from Queue import Queue

import ioxclient
import modbus

pid = "/tmp/ioxclient.pid"
port = 65535
secret = 'S#cr#t'
ioxregd_server = '127.0.0.1'
client = ""
m = ""
q = Queue()

threads = []

foreground = False
c = {}
c["voltage"] = False
c["temperature"] = False
c["humidity"] = False
c["rpm"] = False

def signal_handler(signal, frame):
        ioxregd.log.info("KILLED BY CTRL+C")
        sys.exit(0)

def main():
    client = ioxclient.Ioxclient(ioxregd_server, port, secret,c,q)
    client.loop()
    m = modbus.Modbus(5,q,ioxclient.log)
    m.loop()

signal.signal(signal.SIGINT, signal_handler)

try:
    opts, args = getopt.getopt(sys.argv[1:],"hfTHVR",["foreground","help","voltage","temperature","humidity","rpm"])
except getopt.GetoptError:
    print 'server.py -h'
    sys.exit(2)

for opt, arg in opts:
  if opt == '-h':
     print 'server.py -f -T -H -V -R'
     sys.exit()
  elif opt in ("-f", "--foreground"):
     foreground = True
  elif opt in ("-V", "--voltage"):
     c["voltage"] = True
  elif opt in ("-H", "--humidity"):
     c["humidity"] = True
  elif opt in ("-T", "--temperature"):
     c["temperature"] = True
  elif opt in ("-R", "--rpm"):
     c["rpm"] = True

main()

daemon = Daemonize(app="ioxclient", pid=pid, action=main, chdir="./", logger=ioxclient.log, keep_fds=[ioxclient.fh.stream.fileno()], foreground=foreground)
daemon.start()