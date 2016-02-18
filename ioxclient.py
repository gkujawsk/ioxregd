import logging
import asyncore
import socket
import sqlite3
import datetime
import json
import ssl
import select
import inspect

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
# create file handler which logs even debug messages
fh = logging.FileHandler('/tmp/ioxclient.log')
fh.setLevel(logging.DEBUG)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)
# add the handlers to logger
log.addHandler(ch)
log.addHandler(fh)

BACKLOG                 = 5
SIZE                    = 1024

TEMP_HIGH_TRESHOLD = 32
TEMP_LOW_TRESHOLD = 15
HUMIDITY_HIGH_TRESHOLD = 60
HUMIDITY_LOW_TRESHOLD = 30
VOLTAGE_HIGH_TRESHOLD = 8
VOLTAGE_LOW_TRESHOLD = 0
RPM_HIGH_TRESHOLD = 120
RPM_LOW_TRESHOLD = 20
POLLING_INTERVAL = 5


class Ioxclient(asyncore.dispatcher):

    def __init__(self, host, port, secret,c):
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        log.debug("trying to connect: address=%s:%s" % (host, port))

        pair = self.connect((host,port))
        (conn_sock, client_addr) = pair
        conn_sock = ssl.wrap_socket(conn_sock, server_side=False, do_handshake_on_connect=False)

        while True:
            try:
                self.conn_sock.do_handshake()
                break
            except ssl.SSLError as err:
                if err.args[0] == ssl.SSLWantReadError:
                    select.select([self.conn_sock],[],[])
                elif err.args[0] == ssl.SSLWantWriteError:
                    select.select([],[self.conn_sock],[])
                else:
                    raise
        self.secret = secret
        self.buffer = ""
        self.region = ""
        self.name = ""
        self.c = c
        self.method_register()

    def handle_connect(self):
        log.debug("%s called" % (self.whoami()))

    def handle_close(self):
        log.debug("%s called" % (self.whoami()))
        self.close()

    def handle_read(self):
        data = self.recv(8192)
        log.debug('handle_read() -> %d bytes', len(data))
        self.send(data)

    def handle_write(self):
        log.debug("handle_write called")
        sent = self.send(self.buffer)
        self.buffer = self.buffer[sent:]

    def writable(self):
        return (len(self.buffer) > 0)

    def method_register(self):
        packet = {}
        log.debug("%s called" % (self.whoami()))
        packet["method"] = "REGISTER"
        packet["name"] = self.get_name()
        packet["secret"] = self.secret
        packet["region"] = self.get_region()
        packet["c"] = self.c
        jasoned_packet = json.dumps(packet)
        self.send(jasoned_packet)

    def get_name(self):
        log.debug("%s called" % (self.whoami()))
        if not self.name:
            self.get_snmp()
        return self.name

    def get_region(self):
        log.debug("%s called" % (self.whoami()))
        if not self.region:
            self.get_snmp()
        return self.region

    def get_snmp(self):
        log.debug("%s called" % (self.whoami()))
        self.name = "phony-rtr"
        self.region = "intercity premium gdansk"

    def client_forever(self):
        asyncore.loop()

    def whoami(self):
        return inspect.stack()[1][3]