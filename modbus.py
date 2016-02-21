import threading
import time

#logging.basicConfig(level=logging.DEBUG,
#                    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
#                    )
class Modbus(threading.Thread):
    def __init__(self,i,q,log):
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

    def run(self):
        self.log.debug('Starting with interval %s' % (self.c["interval"]))
        while True:
            time.sleep(int(self.c["interval"]))
            self.log.debug("Current interval is %s" % self.c["interval"])
            while True:
                try:
                    pdu = self.q.get(False)
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