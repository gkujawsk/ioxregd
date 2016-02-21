import asyncore
import datetime
import json
import logging
import select
import socket
import sqlite3
import ssl

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
# create file handler which logs even debug messages
fh = logging.FileHandler('/tmp/ioxregd.log')
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

class EchoHandler(asyncore.dispatcher_with_send):
    def __init__(self, c, conn_sock, client_addr, server):
        self.currentRid = ""
        self.server = server
        self.c = c
#        self.conn_sock = conn_sock
        self.conn_sock = ssl.wrap_socket(conn_sock, keyfile='ioxregd.key', certfile='ioxregd.crt',server_side=True, \
                                         do_handshake_on_connect=False)
        self.rids = {}
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
        self.client_addr = client_addr
        self.out_buffer = ""
        self.is_writable = False
        self.name = ""
        asyncore.dispatcher.__init__(self,self.conn_sock)
        log.debug("created handler; waiting for loop")

    def readable(self):
        return True

    def writable(self):
        return self.is_writable;

    def handle_read(self):
        log.debug("handle_read")
        data = self.recv(8192).strip()
        log.debug('%s from %s' % (data, self.addr))
        try:
            pdu = json.loads(data)
            if(pdu['method'] == "REGISTER"):
                self.method_register(pdu)
            elif(pdu['method'] == "DEREGISTER"):
                self.method_deregister(pdu)
            elif(pdu['method'] == "QUERY"):
                self.method_query(pdu)
            elif(pdu['method'] == "MANAGE"):
                self.method_manage(pdu)
            elif(pdu['method'] == "REPLY"):
                self.method_reply(pdu)
            elif(pdu['method'] == "QUERY"):
                self.method_query(pdu)
            else:
                log.debug("handle_read(): invalid method")
        except ValueError:
            log.debug("Decoding JSON failed.")

    def handle_close(self):
        log.debug("handle_close")
        log.info("conn_closed: client_address=%s:%s" % (self.client_addr[0], self.client_addr[1]))
        self.c.execute("DELETE FROM devices WHERE ip = ? AND port = ?",(self.client_addr[0],self.client_addr[1]))
        self.close()
        #pass

    def method_reply(self,pdu):
        log.debug("method_reply() called")
        if "rid" in pdu:
            rid = pdu["rid"]
            jasoned_pdu = json.dumps(pdu) + "\n"
            self.server.registered_rids[rid].send(jasoned_pdu)

    def method_register(self,pdu):
        log.debug("method_register: called")
        self.currentRid = pdu['rid']
        self.name = pdu['name']
        try:
            self.c.execute("SELECT * FROM devices WHERE ip = ? AND port = ?",(self.client_addr[0],self.client_addr[1]))
        except sqlite3.Error as e:
            log.debug("method_register: %s" % e.args[0])
        if(self.c.fetchone()):
            log.info("method_register: only one registration allowed for ip:port combination")
            self.status_500("Only one registration allowed")
        else:
            if('name' in pdu and 'region' in pdu and 'secret' in pdu):
                if (pdu['secret'] == self.server.secret):
                    self.c.execute("INSERT INTO devices (ip, port, name, date, region) VALUES(?,?,?,?,?)", \
                              (self.client_addr[0],self.client_addr[1],pdu['name'],  datetime.datetime.today(), pdu['region']))
                    self.server.registered_clients[pdu['name']] = self
                    log.debug("method_register: client registered successfuly")
                    self.status_200()
                else:
                    log.info("method_register: Secret mismatch")
                    self.status_500("Secret mismatch")
            else:
                log.info("method_register: Missing attributes")
                self.status_500("Missing attributes")

    def method_deregister(self,pdu):
        log.debug("method_deregister: called")
        self.c.execute("DELETE FROM devices WHERE ip = ? AND port = ?",(self.client_addr[0],self.client_addr[1]))
        self.status_200()

    def method_query(self,pdu):
        log.debug("method_query: called")
        if self.client_registered(self.name) :
          self.c.execute("SELECT * FROM devices WHERE name = ?",[self.name])
          headers = ["ip","port","name","region","date", "temp_high_treshold", "temp_low_treshold", \
                     "humidity_high_treshold","humidity_low_treshold","voltage_high_treshold", \
                     "voltage_low_treshold", "rpm_high_treshold", "rpm_low_treshold", "alert", "polling_interval" \
                     ]
          row = self.c.fetchone()
          response_pdu = {}

          for i in range(len(headers)):
              response_pdu[headers[i]] = row[i]
          jasoned_pdu = json.dumps(response_pdu)
          self.send(jasoned_pdu+"\n")

        else:
            log.debug("method_query: cannot query if not registered")
            self.status_500("Client not registered")

    def method_manage(self,pdu):
        log.info("method_manage: called")
        password = self.server.password
        username = self.server.username
        if ('username' in pdu and 'password' in pdu):
            if (pdu['password'] == password and pdu['username'] == username):
                log.info("method_manage: successfuly authenticated")
                if('operation' in pdu):
                    rid = pdu["rid"]
                    self.server.registered_rids[rid] = self

                    if(pdu['operation'] == "list"):
                        self.operation_list(pdu)
                    elif(pdu['operation'] == "set_treshold"):
                        self.operation_mux(pdu)
                    elif(pdu['operation'] == "set_alert"):
                        self.operation_mux(pdu)
                    elif(pdu['operation'] == "query"):
                        self.operation_mux(pdu)
                    else:
                        log.info("method_manage: Operation invalid")
                        self.status_500("Operation invalid")
                else:
                    log.info("method_manage: operation not specified")
                    self.status_500("Operation not specified")
            else:
                log.info("method_manage: authentication failed")
                self.status_500("Authentication failed")
        else:
            log.info("method_manage: No username or no password")
            self.status_500("Authorization required")

    def method_unknown(self,pdu):
        log.debug("method_unknown: called")
        self.status_500("Not implemended")

    def operation_list(self,pdu):
        log.debug("operation_list: called")
        self.c.execute("SELECT * from devices")
        rows = self.c.fetchall()
        pdu = {}
        devices_array = []
        pdu['status'] = "200"
        for row in rows:
            devices_array.append({"ip":row[0],"port":row[1],"name":row[2],"date":row[3]})
        pdu['data'] = devices_array
        jasoned_pdu = json.dumps(pdu)
        self.send(jasoned_pdu +"\n")

    def operation_mux(self,pdu):
        log.debug("operation_mux: called")
        if('name' in pdu):
            if self.client_registered(pdu['name']):
                if(pdu['operation'] == "set_treshold"):
                    self.operation_set_threshold(pdu)
                elif(pdu['operation'] == "set_alert"):
                    self.operation_set_alert(pdu)
                elif(pdu['operation'] == "query"):
                    self.operation_query(pdu)
            else:
                log.debug("operation_set: device name not registered")
                self.status_500("device name not registered")
        else:
            log.debug("operation_set: device name missing")
            self.status_500("device name missing")

    def operation_set_alert(self,pdu):
        log.debug("operation_set_alert: called")
        allowed_alert_inputs = ["temp", "humidity", "voltage", "rpm"]
        stm = "UPDATE devices SET alert = ? WHERE name = ?"
        bind_values = []
        if pdu['params'] in allowed_alert_inputs:
            bind_values.append(pdu['params'])
            bind_values.append(pdu['name'])
            self.c.execute(stm, bind_values)
            log.debug("operation_set_alert: alerting for %s tresholds" % pdu['params'])
            self.operation_set_send(pdu)
        else:
            log.debug("operation_set_alert: %s is unknown alert input" % pdu['params'])
            self.status_500("Unknown alert input")

    def operation_set_threshold(self,pdu):
        log.debug("operation_set_threshold: called")
        allowed_attribs = ["temp","humidity","voltage","rpm","interval"]
        allowed_tresholds = ["low", "high"]
        stm = "UPDATE devices SET "
        set_stm = ""
        where_stm = "WHERE name = ?"
        bind_values = []
        for attrib in pdu['params']:
            if(attrib in allowed_attribs):
                log.debug("operation_set: attribute %s accepted" % attrib)
                for treshold in pdu['params'][attrib]:
                    if(treshold in allowed_tresholds):
                        log.debug("operation_set: tresholds %s accepted for %s attribute" % (treshold, attrib))
                        set_stm += " " + attrib + "_" + treshold + "_treshold = ?, "
                        bind_values.append(pdu['params'][attrib][treshold])
                    else:
                        set_stm += " interval = ?, "
                        bind_values.append(pdu['params'][attrib])

            else:
                log.debug("operation_set: attribute unknown")
                self.status_500("Attribute unknown")

        set_stm = set_stm[:-2]
        stm += set_stm + " " + where_stm
        bind_values.append(pdu['name'])
        self.c.execute(stm, bind_values)
        self.operation_set_send(pdu)

    def operation_set_send(self,pdu):
        name = pdu['name']
        del pdu['username']
        del pdu['password']
        del pdu['name']
        jasoned_pdu = json.dumps(pdu)+"\n"
        self.server.registered_clients[name].send(jasoned_pdu)
        #self.status_200()

    def operation_query(self,pdu):
        log.debug("operation_query called")
        if "name" in pdu:
            packet = {"method":"QUERY"}
            jasoned_pdu = json.dumps(packet)+"\n"
            self.server.registered_clients[pdu["name"].send(jasoned_pdu)]
            log.debug("operation_query: query send to %s" % (pdu["name"]))
            self.status_200()
        else:
            log.debug("operation_query: missing name attribute")
            self.status_500("Missing name attribute")

    def client_registered(self,name):
        self.c.execute("SELECT * FROM devices WHERE name = ?",[name])
        if self.c.fetchone():
            return True

    def status_200(self, desc="OK"):
        self.send('{"method":"REPLY", "status": "200", "desc": "' + desc + '","rid":"'+self.currentRid+'"}\n')

    def status_500(self, desc="ERROR"):
        self.send('{"method":"REPLY", "status": "500", "desc": "' + desc + '","rid":"'+self.currentRid+'"}\n')

class Ioxregd(asyncore.dispatcher):

    def __init__(self, host, port, username, password, secret):
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind((host, port))
        self.username = username
        self.password = password
        self.secret = secret
        log.debug("bind: address=%s:%s" % (host, port))
        self.listen(5)
        self.registered_clients = {}
        self.registered_rids = {}
        self.remote_clients = []
        self.conn = ""
        self.c = ""
        self.database()

    def handle_accept(self):
        log.debug("handle_accept")
        pair = self.accept()
        if pair is None:
            pass
        else:
            (conn_sock, client_addr) = pair
            log.debug("Incoming connection from %s" % repr(client_addr))
            self.remote_clients.append(EchoHandler(self.c,conn_sock,client_addr,self))

    def server_forever(self):
        asyncore.loop()

    def database(self):
        self.conn = sqlite3.connect('./ioxregd.db',isolation_level=None)
        self.c = self.conn.cursor()
        try:
            self.c.execute("DROP TABLE IF EXISTS devices")
            self.c.execute("CREATE TABLE devices (ip text, port text, name text, region text, date text, \
                temp_high_treshold default '%s', temp_low_treshold default '%s', \
                humidity_high_treshold default '%s', humidity_low_treshold default '%s', \
                voltage_high_treshold default '%s', voltage_low_treshold default '%s', \
                rpm_high_treshold default '%s', rpm_low_treshold default '%s', \
                alert default 'none', interval default  %s\
                )" % (TEMP_HIGH_TRESHOLD, TEMP_LOW_TRESHOLD, \
                      HUMIDITY_HIGH_TRESHOLD, HUMIDITY_LOW_TRESHOLD,\
                      VOLTAGE_HIGH_TRESHOLD, VOLTAGE_LOW_TRESHOLD,\
                      RPM_HIGH_TRESHOLD, RPM_LOW_TRESHOLD,\
                      POLLING_INTERVAL))
        except sqlite3.Error as e:
            log.debug("sqlite: %s" % e.args[0])
