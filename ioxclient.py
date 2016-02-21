import asyncore
import inspect
import json
import logging
import socket
import ssl
import threading
import time
import uuid

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
# create file handler which logs even debug messages
fh = logging.FileHandler('/tmp/ioxclient.log')
fh.setLevel(logging.DEBUG)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - (%(threadName)-10s) - %(message)s')
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


class Ioxclient(asyncore.dispatcher, threading.Thread):
    want_read = want_write = True
    established = False
    def __init__(self, host, port, secret,c,q):
        asyncore.dispatcher.__init__(self)
        threading.Thread.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        log.debug("trying to connect: address=%s:%s" % (host, port))
        self.connect((host,port))
        self.secret = secret
        self.q = q
        self.buffer = ""
        self.region = ""
        self.name = ""
        self.c = c
        self.registered = False
        self.maxRetries = 3
        self.lastMethod = {}

    def _handshake(self):
        try:
            log.debug("_handshake() will try to do handshake")
            self.socket.do_handshake()
        except ssl.SSLWantReadError:
            log.debug("_handshake() SSLWantReadError")
            self.want_read = True;
        except ssl.SSLWantWriteError:
            log.debug("_handshake() SSLWantWriteError")
            self.want_write = True
        except ssl.SSLError as err:
            log.debug("_handshake() raising %s" % (err.strerror))
            raise
        else:
            self.want_read = True
            self.want_write = False
            self.established = True
            self.initialize()

    def handle_connect(self):
        log.debug("%s called" % (self.whoami()))
        log.debug("wraping the socket")
        self._socket = self.socket
        self.socket = ssl.wrap_socket(self._socket, do_handshake_on_connect=False)
        log.debug("socket wrapped:")

    def handle_close(self):
        log.debug("%s called" % (self.whoami()))
        self.close()

    def handle_read(self):
        if self.established:
            log.debug("handle_read() and established")
            data = self.recv(8192).strip()
            try:
                pdu = json.loads(data)
                if "method" in pdu:
                    log.debug("handle_read(): METHOD %s received" % (pdu['method']))
                    if(pdu['method'] == "REPLY"):
                        self.method_REPLY(pdu)
                    elif(pdu['method'] == "MANAGE"):
                        self.method_manage(pdu)
                    else:
                        self.method_unknown(pdu)
                else:
                    log.debug("handle_read: No method attribute specified")
                    self.status_500("No method attribute specified")
            except ValueError:
                log.debug("Decoding JSON failed.")
                self.status_500("Malformed packet received")
        else:
            log.debug("handle_read handshake required")
            self._handshake()


    def handle_write(self):
        if self.established:
            log.debug("handle_write() and established")
            log.debug("handle_write() called")
            #sent = self.send(self.buffer)
#           #self.buffer = self.buffer[sent:]
        else:
            log.debug("handle_write handshake required")
            self._handshake()

    def writable(self):
        if self.established:
            return (len(self.buffer) > 0)
        else:
            return True

    def readable(self):
        return True;

    def initialize(self):
        self.method_register()

    def method_REPLY(self,pdu):
        log.debug("method_REPLY() called")
        if "status" in pdu:
            log.debug("method_REPLY() status = %s" % (pdu["status"]))
            if "rid" in pdu and "desc" in pdu:
                if pdu["rid"] in self.lastMethod:
                    if pdu["status"] == "200":
                        self.REPLY_200(pdu)
                    elif pdu["status"] == "500":
                        self.REPLY_500(pdu)
                    else:
                        log.debug("method_REPLY() UNKNOWN status attribute %s" % pdu["status"])
                else:
                    log.debug("method_REPLY() Rid %s unknown. Discarding." % (pdu["rid"]))
            else:
                log.debug("method_REPLY() Rid or desc attribute not specified")
        else:
            log.debug("method_REPLY() Status attribute not specified")

    def method_manage(self,pdu):
        log.debug("method_manage() called")
        if('operation' in pdu):
            if(pdu['operation'] == "set_treshold"):
                self.operation_set_threshold(pdu)
            elif(pdu['operation'] == "set_alert"):
                self.operation_set_alert(pdu)
            elif(pdu['operation'] == "query"):
                self.operation_query(pdu)
            else:
                log.info("method_manage: Operation attribute invalid")
                self.status_500("Operation attribute invalid")
        else:
            log.debug("method_manage() operation attribute not specified")
            self.status_500("Operation attribute not specified")

    def REPLY_500(self,pdu):
        log.debug("REPLY_500() called")
        log.debug("REPLY_500() Status %s desc %s for rid %s (%s)" % \
                  (pdu["status"],pdu["desc"],pdu["rid"], self.lastMethod[pdu["rid"]]))
        if self.lastMethod[pdu["rid"]] == "REGISTER":
            log.debug("reply_500() retrying registration afrer 1s sleep")
            time.sleep(1)
            self.method_register()

    def REPLY_200(self,pdu):
        log.debug("REPLY_200() called")
        log.debug("REPLY_200() Status %s desc %s for rid %s (%s)" % \
                  (pdu["status"],pdu["desc"],pdu["rid"], self.lastMethod[pdu["rid"]]))
        if self.lastMethod[pdu["rid"]] == "REGISTER":
            log.debug("REPLY_200() registration successful")
            self.registered = True

    def operation_set_threshold(self,pdu):
        log.debug("operation_set_threshold() called")
        log.debug("operation_set_threshold() RID %s" % (pdu["rid"]) )
        self.q.put(pdu)
        self.status_200("New thresholds accepted by iox",pdu["rid"] )

    def operation_set_alert(self,pdu):
        log.debug("operation_set_alert() called")
        allowed_alert_inputs = ["temp", "humidity", "voltage", "rpm"]
        if pdu['params'] in allowed_alert_inputs:
            self.q.put(pdu)
            self.status_200("New alert settings accepted by iox",pdu["rid"])
        else:
            log.debug("operation_set_alert: %s is unknown alert input" % pdu['params'])
            self.status_500("Unknown alert input",pdu["rid"])

    def operation_query(self,pdu):
        log.debug("operation_query() called")

    def method_register(self):
        if not self.registered and self.maxRetries > 0:
            packet = {}
            log.debug("%s called" % (self.whoami()))
            packet["method"] = "REGISTER"
            packet["name"] = self.get_name()
            packet["secret"] = self.secret
            packet["region"] = self.get_region()
            packet["c"] = self.c
            packet["rid"] = str(uuid.uuid4().hex)
            jasoned_packet = json.dumps(packet)
            self.send(jasoned_packet)
            self.lastMethod[packet["rid"]] = packet["method"]
            self.maxRetries -= 1
        elif not self.registered and self.maxRetries == 0:
            log.debug("method_registered() Max registration retries reached. Giving up.")
            exit(2)
        else:
            log.debug("method_registered() Already registered")

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

    def run(self):
        self.client_forever()

    def loop(self):
        self.start()

    def whoami(self):
        return inspect.stack()[1][3]

    def status_200(self, desc="OK",rid=""):
        self.send('{"method":"REPLY", "status": "200", "rid": "'+rid+'", "desc": "' + desc + '"}\n')

    def status_500(self, desc="ERROR",rid=""):
        self.send('{"method":"REPLY", "status": "200", "rid": "'+rid+'", "desc": "' + desc + '"}\n')

    def method_unknown(self,pdu):
        log.debug("method_unknown: called")
        self.status_500("Method %s not implemended" %(pdu['method']))