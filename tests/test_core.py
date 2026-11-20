import base64
import datetime as dt
import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from voicedesk.logic import classify
from voicedesk.store import Store, ValidationError, ConflictError
from voicedesk.api import make_handler, twilio_valid

KEY = "this-is-only-a-local-unit-test-secret"

def next_weekday(days=2):
    day=dt.datetime.now(ZoneInfo("UTC")).date()+dt.timedelta(days=days)
    while day.weekday()>4: day+=dt.timedelta(days=1)
    return day.isoformat()

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/"data.db")
    def tearDown(self): self.tmp.cleanup()
    def test_lead_persisted_and_summary(self):
        result=self.store.create_lead({"name":"Alex","contact":"alex@example.test","interest":"Consultation"})
        self.assertEqual(result["status"],"new")
        self.assertEqual(self.store.summary()["total_leads"],1)
        self.assertEqual(self.store.list_leads()[0]["contact"],"alex@example.test")
    def test_invalid_lead(self):
        with self.assertRaises(ValidationError): self.store.create_lead({"name":"","contact":"phone"})
        with self.assertRaises(ValidationError): self.store.create_lead({"name":"x"*101,"contact":"phone"})
    def test_booking_and_double_slot(self):
        request={"date":next_weekday(),"time":"10:00","name":"Alex","contact":"alex@example.test"}
        self.assertEqual(self.store.create_appointment(request)["status"],"requested")
        with self.assertRaises(ConflictError): self.store.create_appointment(request)
    def test_invalid_slots(self):
        for date,time in [("2020-01-01","10:00"),(next_weekday(),"22:00"),(next_weekday(),"10:15"),("2026-02-30","10:00")]:
            with self.subTest(date=date,time=time),self.assertRaises(ValidationError):
                self.store.create_appointment({"date":date,"time":time,"name":"Test","contact":"12345"})
    def test_time_past(self):
        with self.assertRaises(ValidationError):
            self.store.create_appointment({"date":dt.datetime.now().date().isoformat(),"time":"00:00","name":"X","contact":"12345"})

class IntentTests(unittest.TestCase):
    def test_intents(self):
        for phrase,intent in [("book an appointment","booking"),("how much does it cost","pricing"),("opening hours","hours"),("speak to a human","human"),("directions and parking","location"),("hello","general"),("","clarify")]:
            with self.subTest(phrase=phrase): self.assertEqual(classify(phrase)[0],intent)

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.store=Store(Path(cls.tmp.name)/"integration.sqlite3")
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(cls.store,KEY,"twilio-test-key","https://voice.example.test"))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
    def req(self,method,path,body=None,auth=True,extra=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        headers=dict(extra or {})
        if auth: headers["Authorization"]="Bearer "+KEY
        if isinstance(body,dict):
            body=json.dumps(body);headers["Content-Type"]="application/json"
        conn.request(method,path,body=body,headers=headers)
        res=conn.getresponse();raw=res.read()
        content=raw.decode("utf-8");ct=res.getheader("Content-Type","")
        result=json.loads(content) if ct.startswith("application/json") else content
        status=res.status;conn.close()
        return status,result
    def test_health_and_frontend(self):
        status,data=self.req("GET","/api/health",auth=False)
        self.assertEqual(status,200)
        self.assertEqual(data["assistant_mode"],"rules")
        status,html=self.req("GET","/",auth=False)
        self.assertEqual(status,200);self.assertIn("NextGen VoiceDesk",html)
        status,js=self.req("GET","/app.js",auth=False)
        self.assertEqual(status,200);self.assertIn("browser-only",js)
    def test_auth_and_restricted_files(self):
        self.assertEqual(self.req("GET","/api/leads",auth=False)[0],401)
        self.assertEqual(self.req("POST","/api/leads",{"name":"N","contact":"12345"},auth=False)[0],401)
        self.assertEqual(self.req("GET","/.env",auth=False)[0],404)
        self.assertEqual(self.req("GET","/api/unknown",auth=False)[0],404)
    def test_leads_and_summary(self):
        status,new=self.req("POST","/api/leads",{"name":"Test Person","contact":"test@example.test","interest":"Pricing"})
        self.assertEqual(status,201)
        self.assertIn("id",new)
        status,leads=self.req("GET","/api/leads")
        self.assertEqual(status,200);self.assertTrue(any(l["contact"]=="test@example.test" for l in leads["items"]))
        self.assertEqual(self.req("GET","/api/summary")[0],200)
    def test_appointments_and_conflict(self):
        payload={"name":"Sarah","contact":"sarah@example.test","date":next_weekday(4),"time":"14:30","service":"Consultation"}
        self.assertEqual(self.req("POST","/api/appointments",payload)[0],201)
        self.assertEqual(self.req("POST","/api/appointments",payload)[0],409)
        self.assertEqual(self.req("GET","/api/appointments")[0],200)
    def test_message(self):
        status,payload=self.req("POST","/api/message",{"message":"Can I book an appointment?"})
        self.assertEqual(status,200)
        self.assertEqual(payload["intent"],"booking")
        self.assertFalse(payload["booking_confirmed"])
        self.assertEqual(payload["mode"],"rules")
    def test_invalid_content_type_and_non_object(self):
        self.assertEqual(self.req("POST","/api/leads",body="not json",extra={"Content-Type":"text/plain"})[0],400)
        self.assertEqual(self.req("POST","/api/message",body="[]",extra={"Content-Type":"application/json"})[0],400)
        self.assertEqual(self.req("POST","/api/message",body="x"*9000,extra={"Content-Type":"application/json"})[0],400)
    def test_twilio_signature_and_signed_flow(self):
        form={"CallSid":"CA123456","From":"+15551234567","To":"+15557654321"}
        body=urlencode(form)
        url="https://voice.example.test/twilio/voice"
        string=url+"".join(k+form[k] for k in sorted(form))
        sig=base64.b64encode(hmac.new(b"twilio-test-key",string.encode(),hashlib.sha1).digest()).decode()
        self.assertTrue(twilio_valid(sig,url,form,"twilio-test-key"))
        self.assertEqual(self.req("POST","/twilio/voice",body=body,auth=False,extra={"Content-Type":"application/x-www-form-urlencoded","X-Twilio-Signature":"wrong"})[0],403)
        status,xml=self.req("POST","/twilio/voice",body=body,auth=False,extra={"Content-Type":"application/x-www-form-urlencoded","X-Twilio-Signature":sig})
        self.assertEqual(status,200);self.assertIn("<Gather",xml);self.assertIn("automated receptionist",xml)
        form["SpeechResult"]="How much does it cost?"
        body=urlencode(form);url="https://voice.example.test/twilio/collect"
        string=url+"".join(k+form[k] for k in sorted(form))
        sig=base64.b64encode(hmac.new(b"twilio-test-key",string.encode(),hashlib.sha1).digest()).decode()
        status,xml=self.req("POST","/twilio/collect",body=body,auth=False,extra={"Content-Type":"application/x-www-form-urlencoded","X-Twilio-Signature":sig})
        self.assertEqual(status,200);self.assertIn("Pricing depends",xml)
        self.assertTrue(any(lead["source"]=="twilio" for lead in self.store.list_leads()))

if __name__=="__main__":unittest.main()
