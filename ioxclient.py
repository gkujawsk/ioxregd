# -*- coding: utf-8 -*-
import asyncore
import datetime
import inspect
import json
import logging
import smtplib
import socket
import ssl
import struct
import threading
import time
import uuid

import Queue
import pynmea2
import requests
from alerta.alert import Alert
from alerta.api import ApiClient
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText

smsapi_notification = "48608652741"
smsapi_username = "gkujawsk"
smsapi_password = "8cbdb6cb801a22be2dd834fa4d461d28"
email_server = "smtp.gmail.com"
email_server_port = 587
email_from = "ioxclient@gmail.com"
email_to = "ioxoperator@gmail.com"
email_user = "ioxclient@gmail.com"
email_password = "Csco100c"

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


    def __init__(self, host, port, secret,slaves,q, name="",region="",gps=False):
        asyncore.dispatcher.__init__(self)
        threading.Thread.__init__(self)
        self.alerta_key = None
        self.gps = gps
        self.gps_sock = None
        self.gps_position = None
        self.alerta = ApiClient(endpoint="http://archangel-02.brama.waw.pl:8080")
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        log.debug("trying to connect: address=%s:%s" % (host, port))
        self.connect((host,port))
        self.secret = secret
        self.q = q
        self.registration_date = None
        self.buffer = ""
        self.m = None
        self.attached = False
        self.region = region
        self.name = name
        self.slaves = slaves
        self.registered = False
        self.maxRetries = 3
        self.lastMethod = {}
        self.notification_channels = []
        if self.gps:
            self.gps_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            print self.gps_sock
            self.gps_sock.bind (("0.0.0.0",65534))
            print self.gps_sock
            self.gps_sock.settimeout(0.1)
    def is_attached(self):
        return self.attached

    def attach(self,m):
        self.m = m
        self.attached = True

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
        self.m.giveup = True
        log.info("ioxregd server connection lost")
        self.close()

    def handle_read(self):
        if self.established:
#            log.debug("handle_read() and established")
            try:
                data = self.recv(8192).strip()
            except socket.error as e:
                log.info("ioxclient.py:handle_read(): %s" % (e.strerror))
                exit()
            try:
                pdu = json.loads(data)
                if "method" in pdu:
                    if not pdu['method'] == "HEARTBEAT":
                        log.debug("handle_read(): METHOD %s received" % (pdu['method']))
                    if(pdu['method'] == "REPLY"):
                        self.method_reply(pdu)
                    elif(pdu['method'] == "MANAGE"):
                        self.method_manage(pdu)
                    elif(pdu['method'] == "HEARTBEAT"):
                        self.method_heartbeat(pdu)
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

    def method_heartbeat(self,pdu):
#        log.debug("method_heartbeat() called")
        self.send(json.dumps(pdu))

    def handle_write(self):
        log.debug("handle_write() called")
        if self.established:
            log.debug("handle_write() and established")
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

    def set_gps_msg(self):
        #log.debug("ioxclient.py:get_gps_position() called")
        data = None
        try:
            data, addr = self.gps_sock.recvfrom(1024)
        except socket.timeout:
            pass
        if data:
            log.debug("ioxclient.py:get_gps_position() Got some data")
            try:
                msg = pynmea2.parse(data)
                self.gps_position = {"altitude":msg.altitude,
                                     "lat":msg.latitude,
                                     "latitude":'%02d°%02d′%07.4f″' % (msg.latitude, msg.latitude_minutes, msg.latitude_seconds),
                                     "lat_dir":msg.lat_dir,
                                     "lon":msg.longitude,
                                     "longitude":'%02d°%02d′%07.4f″' % (msg.longitude, msg.longitude_minutes, msg.longitude_seconds),
                                     "lon_dir":msg.lon_dir}
                print self.gps_position
            except ValueError:
                #log.debug("ioxclient.py:get_gps_position() Parse error")
                pass

    def method_reply(self,pdu):
        log.debug("method_reply() called")
        if "status" in pdu:
            log.debug("method_reply() status = %s" % (pdu["status"]))
            if "rid" in pdu and "desc" in pdu:
                if pdu["rid"] in self.lastMethod:
                    if pdu["status"] == "200":
                        self.reply_200(pdu)
                    elif pdu["status"] == "500":
                        self.reply_500(pdu)
                    else:
                        log.debug("method_reply() UNKNOWN status attribute %s" % pdu["status"])
                else:
                    log.debug("method_reply() Rid %s unknown. Discarding." % (pdu["rid"]))
            else:
                log.debug("method_reply() Rid or desc attribute not specified")
        else:
            log.debug("method_reply() Status attribute not specified")

    def method_manage(self,pdu):
        log.debug("method_manage() called")
        if('operation' in pdu):
            if(pdu['operation'] == "set"):
                self.operation_set(pdu)
            elif(pdu['operation'] == "details"):
                self.operation_details(pdu)
            else:
                log.info("method_manage: Operation attribute invalid")
                self.status_500("Operation attribute invalid")
        else:
            log.debug("method_manage() operation attribute not specified")
            self.status_500("Operation attribute not specified")

    def reply_500(self,pdu):
        log.debug("reply_500() called")
        log.debug("reply_500() Status %s desc %s for rid %s (%s)" % \
                  (pdu["status"],pdu["desc"],pdu["rid"], self.lastMethod[pdu["rid"]]))
        if self.lastMethod[pdu["rid"]] == "REGISTER":
            log.debug("reply_500() retrying registration afrer 1s sleep")
            time.sleep(1)
            self.method_register()

    def reply_200(self,pdu):
        log.debug("reply_200() called")
        log.debug("reply_200() Status %s desc %s for rid %s (%s)" % \
                  (pdu["status"],pdu["desc"],pdu["rid"], self.lastMethod[pdu["rid"]]))
        if self.lastMethod[pdu["rid"]] == "REGISTER":
            self.registration_date = datetime.datetime.today().__str__()
            log.debug("reply_200() registration successful")
            self.registered = True

    def operation_set(self,pdu):
        log.debug("operation_set() called")
#        if "alert" in pdu['params']:
#            self.operation_set_alert(pdu)
#        if "tresholds" in pdu['params']:
#            self.operation_set_threshold(pdu)
        self.q["one"].put(pdu)
        if 'notification' in pdu['params']:
            self.notification_channels = pdu['params']['notification']
        else:
            self.notification_channels = []
        self.status_200("New thresholds, alerts and notification channels accepted",pdu["rid"])

    def operation_set_threshold(self,pdu):
        log.debug("operation_set_threshold() called")
        log.debug("operation_set_threshold() RID %s" % (pdu["rid"]) )
        self.q["one"].put(pdu)
        #self.status_200("New thresholds accepted by iox",pdu["rid"] )

    def operation_set_alert(self,pdu):
        log.debug("operation_set_alert() called")
        allowed_alert_inputs = ["temperature", "humidity", "voltage", "rpm"]
        if pdu['params']['alert'] in allowed_alert_inputs:
            self.q["one"].put(pdu)
            return ("200", "New alert settings accepted by iox")
        else:
            log.debug("operation_set_alert: %s is unknown alert input" % pdu['params']['alert'])
            return ("500", "Unknown alert input")

    def operation_details(self,pdu):
        log.debug("operation_details() called")
        (ip, port) = self.socket.getsockname()
        pdu = {"method":"REPLY","rid":pdu["rid"], "name":self.name, \
               "region":self.region, "date":self.registration_date, \
               "port":port, "ip": ip, \
               "data": {"measurements":self.m.current, \
                        "slaves": self.m.get_slaves(),
                        "alert": self.m.get_alert(),
                        "thresholds": self.m.get_thresholds(),
                        "notification": self.notification_channels,
                        "gps": self.gps_position} \
               }
        jasoned_pdu = json.dumps(pdu)
        self.send(jasoned_pdu)

    def method_register(self):
        if not self.registered and self.maxRetries > 0:
            packet = {}
            log.debug("%s called" % (self.whoami()))
            packet["method"] = "REGISTER"
            packet["name"] = self.get_name()
            packet["secret"] = self.secret
            packet["region"] = self.get_region()
            packet["slaves"] = self.slaves
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
        self.region = "phony region"

        gw = self.get_default_gateway()
        errorIndication, errorStatus, errorIndex, varBinds = next(
                getCmd(SnmpEngine(),
                       CommunityData('iox'),
                       UdpTransportTarget((gw, 161)),
                       ContextData(),
                       ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')),
                       ObjectType(ObjectIdentity('1.3.6.1.2.1.1.6.0')))
        )

        if errorIndication:
            log.info("get_snmp() " + errorIndication)
        elif errorStatus:
            log.info('get_snmp() %s at %s' % (errorStatus.prettyPrint(), errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
        else:
            self.name = varBinds[0][1]
            self.region = varBinds[1][1]
            return [hostname, location]

    def client_forever(self):
        while asyncore.socket_map:
            asyncore.loop(timeout=1, count=1)
            if self.gps:
              self.set_gps_msg()
            if self.is_attached():
                while True:
                    try:
                        a = self.m.alerts.get(False)
                        if a is None:
                            break
                        else:
                            self.send_alert(a)
                    except Queue.Empty:
                        break
        #asyncore.loop()

    def run(self):
        self.client_forever()

    def loop(self):
        self.start()

    def whoami(self):
        return inspect.stack()[1][3]

    def send_alert(self,alert):
        log.info("ALARM: %s" % (alert["desc"]))
        # By default sent alert to alerta
        alert["name"] = self.name
        alert["rid"] = str(uuid.uuid4().hex)
        self.lastMethod[alert["rid"]] = "ALERT"
        jasoned_alert = json.dumps(alert) + "\n"
        # Send to ioxregd server
        self.send(jasoned_alert)
        # Send to alerta server
        self.alerta_alert(alert)
        # Send sms alert
        if("sms" in self.notification_channels):
            self.sms_alert(alert)
        # Send email alert
        if("email" in self.notification_channels):
            self.email_alert(alert)

    def alerta_alert(self,alert):
        try:
            self.alerta.send( Alert(
            resource=self.name,
            event=alert["desc"],
            group=self.region,
            environment='Production',
            service=["iox"],
            value=alert["slave"],
            severity=alert["severity"],
            text="",
            tags=['iox', 'treshold']
            ))
        except requests.ConnectionError as e:
            log.info("ioxclient.py:send_alert(): Alerta connection error %s" % (e.strerror))
        except requests.Timeout as e:
            log.info("ioxclient.py:send_alert(): Alerta connection timeout %s" % (e.strerror))

    def sms_alert(self,alert):
        log.debug("ioxclient.py:sms_alert() called")
        payload = {'username':smsapi_username,'password':smsapi_password,
                   'to':smsapi_notification,
                   'message':alert["desc"]+" "+self.region + ":" + self.name }
        try:
            #requests.get('http://api.smsapi.pl/sms.do', params=payload, timeout=0.5);
            pass
        except requests.ConnectionError as e:
            log.info("ioxclient.py:sms_alert(): Unable to send SMS alert %s" % (e.strerror))
        except requests.Timeout as e:
            log.info("ioxclient.py:sms_alert(): Connection to smsapi.pl timeout %s" % (e.strerror))

    def email_alert(self,alert):
        log.debug("ioxclient.py:email_alert() called")
        msg = MIMEMultipart()
        msg['From'] = email_from
        msg['To'] = email_to
        msg['Subject'] = '[IOX ALERT] ' + alert["desc"] + " " + self.region + ":" + self.name
        message = alert["desc"] + " " + self.region + ":" + self.name
        msg.attach(MIMEText(message))
        try:
            mailserver = smtplib.SMTP(email_server,email_server_port)
            mailserver.ehlo()
            mailserver.starttls()
            mailserver.ehlo()
            mailserver.login(email_user, email_password)
            mailserver.sendmail(email_from,email_to,msg.as_string())
            mailserver.quit()
        except smtplib.SMTPException as e:
            log.info("ioxclient.py:email_alert(): Unable to send email notification %s" % (e.strerror))

    def status_200(self, desc="OK",rid=""):
        self.send('{"method":"REPLY", "status": "200", "rid": "'+rid+'", "desc": "' + desc + '"}\n')

    def status_500(self, desc="ERROR",rid=""):
        self.send('{"method":"REPLY", "status": "200", "rid": "'+rid+'", "desc": "' + desc + '"}\n')

    def method_unknown(self,pdu):
        log.debug("method_unknown: called")
        self.status_500("Method %s not implemended" %(pdu['method']))

    def get_default_gateway(self):
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                    continue
                return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
