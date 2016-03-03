import threading
import time


class Modbus(threading.Thread):
    def __init__(self,i,q,log,slaves):
        threading.Thread.__init__(self)
        self.log = log
        self.q = q
        self.c = { "temp":{"high":"1","low":"20"}, \
                   "rpm":{"high":"1000","low":"200"}, \
                   "humidity":{"low":"0","high":"50"}, \
                   "voltage":{"low":"0","high":"10"}, \
                   "interval":i
                   }
        self.a = None
        self.current = None
        self.slaves = {}
        for address in slaves:
            self.slaves[address] = eval("modbusdevices.Modbus"+slaves[address]+"(address="+address+")")

    def run(self):
        self.log.debug('Starting with interval %s' % (self.c["interval"]))
        while True:
            time.sleep(int(self.c["interval"]))
            self.log.debug("Current interval is %s" % self.c["interval"])
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
        self.log.debug("method_manage() called")
        if "operation" in pdu:
            if pdu["operation"] == "set_treshold":
                self.operation_set_threshold(pdu)
            elif pdu["operation"] == "set_alert":
                self.operation_set_alert(pdu)

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