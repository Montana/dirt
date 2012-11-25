import time
from dirt import DirtApp

class FirstApp(DirtApp):
    def serve_forever(self):
        print "FirstApp is serving forever..."
        time.sleep(100)

class SecondApp(DirtApp):
    def serve_forever(self):
        print "SecondApp is serving forever..."
        time.sleep(100)
