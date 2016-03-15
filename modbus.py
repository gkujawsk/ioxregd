import threading
import time

import requests
from Queue import Queue
from influxdb import InfluxDBClient

requests.packages.urllib3.disable_warnings()

class Modbus(threading.Thread):
    def __init__(self,i,q,log,slaves,):
        threading.Thread.__init__(self)
        self.giveup = False
        self.client = None
        self.log = log
        self.q = q
        self.alerts = Queue()
        self.influxdb = InfluxDBClient(host='archangel-02.brama.waw.pl', port=8086,\
                                       username='root', password='Csco100c',\
                                       database='iox', ssl=True)
        self.c = { "temperature":{"high":"1","low":"20"}, \
                   "rpm":{"high":"1000","low":"200"}, \
                   "humidity":{"low":"0","high":"50"}, \
                   "voltage":{"low":"0","high":"10"}, \
                   "interval":i
                   }
        self.a = None
        self.current = None
        self.slaves = {}
        for address in slaves:
            self.slaves[address] = eval("modbusdevices.Modbus"+slaves[address]+"(self.alerts,address="+address+")")

    def attach(self,client):
        self.client = client

    def run(self):
        self.log.debug('Starting with interval %s' % (self.c["interval"]))
        elapsed = 0
        step = 0.1
        while True:
            if self.giveup:
                self.log.debug("modbus.py:run() giving up")
                break
            time.sleep(step)
            elapsed += step
            self.check_queue()

            if elapsed > self.c["interval"]:
                elapsed = 0
                self.read_slaves()


    def read_slaves(self):
        lock = threading.Lock()
        lock.acquire()
        m = {}
        for s in self.slaves:
            if self.slaves[s].readable:
                try:
                    m.update(self.slaves[s].read(self.slaves[s].input_regs.keys()))
                except IOError:
                    self.log.debug("Modbus:run(): Failed to read from instrument")
        self.current = m
        lock.release()
        influxdb_pdu = []
        for i in m:
            influxdb_pdu.append({"measurement":i,\
                                 "tags":{"host":self.client.name,"region":self.client.region},\
                                 "fields":{"value":float("{0:0.2f}".format(m[i]))}\
                                 })
        try:
            self.influxdb.write_points(influxdb_pdu)
        except:
            self.log.info("read_slaves(): influxdb server communication problems")

    def check_queue(self):
        while True:
            try:
                pdu = self.q["one"].get(False)
                if pdu is None:
                    break
                else:
                    if "method" in pdu:
                        if pdu["method"] == "MANAGE":
                            self.method_manage(pdu)
                        elif pdu["method"] == "QUERY":
                            self.method_query(pdu)
                        else:
                            break
                    else:
                        break
            except:
                break

    def loop(self):
        self.start()

    def get_slaves(self):
        r = {}
        for s in self.slaves:
            r[s] = {"desc": self.slaves[s].desc, "name": self.slaves[s].name}
        return r

    def get_thresholds(self):
        r = {}
        for s in self.slaves:
            r[s] = self.slaves[s].tresholds
        return r

    def get_alert(self):
        return self.a

    def method_manage(self,pdu):
        self.log.debug("modbus.method_manage() called")
        if "operation" in pdu:
            if pdu["operation"] == "set":
                self.operation_set(pdu)

    def operation_set(self,pdu):
        self.log.debug("operation_set() called")
        # Uproszenie 1 - AE1040, 2 - AE1060 3 - ARDUINO RELAYS 4 - ARDUINO RPM
        self.log.debug("operation_set() setting tresholds")
        if "1" in self.slaves:
            self.slaves["1"].tresholds["temperature"] = pdu["params"]["tresholds"]["temperature"]
            self.slaves["1"].tresholds["humidity"] = pdu["params"]["tresholds"]["humidity"]
        if "2" in self.slaves:
            self.slaves["2"].tresholds["voltage"] = pdu["params"]["tresholds"]["voltage"]
        if "4" in self.slaves:
            self.slaves["4"].tresholds["rpm"] = pdu["params"]["tresholds"]["rpm"]
        self.log.debug("operation_set() setting alert for %s" % (pdu["params"]["alert"]))
        self.a = pdu["params"]["alert"]
        self.notification_channels = pdu["params"]["notification"]

    def operation_set_threshold(self,pdu):
        self.log.debug("operation_set_threshold() called")
        self.log.debug("operation_set_threshold() setting new parameters")
        self.c = pdu["params"]

    def operation_set_alert(self,pdu):
        self.log.debug("operation_set_alert() called")
        self.log.debug("operation_set_alert() previous alert setting %s" % (self.a))
        self.a = pdu["params"]
        self.log.debug("operation_set_alert() new alert setting %s" % (self.a))

    def method_query(self,pdu):
        pass