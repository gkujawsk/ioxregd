import ioxregd
import signal
import sys
import getopt
from daemonize import Daemonize

pid = "/tmp/ioxregd.pid"
interface = "0.0.0.0"
port = 65535
username = 'root'
password = 'Csco100c'
secret = 'S#cr#t'
server = ''
foreground = False

def signal_handler(signal, frame):
        ioxregd.log.info("KILLED BY CTRL+C")
        sys.exit(0)

def main():
    server = ioxregd.Ioxregd(interface, port, username, password,secret)
    server.server_forever()

signal.signal(signal.SIGINT, signal_handler)

try:
    opts, args = getopt.getopt(sys.argv[1:],"hf",["foreground","help"])
except getopt.GetoptError:
    print 'server.py -h'
    sys.exit(2)

for opt, arg in opts:
  if opt == '-h':
     print 'server.py -f'
     sys.exit()
  elif opt in ("-f", "--foreground"):
     foreground = True

daemon = Daemonize(app="ioxregd", pid=pid, action=main, chdir="./", logger=ioxregd.log, keep_fds=[ioxregd.fh.stream.fileno()], foreground=foreground)
daemon.start()