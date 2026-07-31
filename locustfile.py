from locust import HttpUser, task, between
import urllib3
urllib3.disable_warnings()  # supprime les warnings SSL dans le terminal

class SupervisionUser(HttpUser):
    wait_time = between(1, 3)
    token = None

    def on_start(self):
        self.client.verify = False  # certificat auto-signé
        resp = self.client.post("/token", data={
            "username": "jean_ope",
            "password": "ope123"
        })
        self.token = resp.json().get("access_token")

    @task(3)
    def get_status(self):
        self.client.get("/api/status", headers={
            "Authorization": f"Bearer {self.token}"
        }, verify=False)

    @task(1)
    def get_root(self):
        self.client.get("/", verify=False)