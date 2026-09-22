import asyncio
import httpx
from pyzeebe import ZeebeWorker, create_insecure_channel

API_BASE = "http://localhost:5000"


async def main():
    channel = create_insecure_channel(grpc_address="localhost:26500")
    worker = ZeebeWorker(channel)

    async with httpx.AsyncClient(base_url=API_BASE, timeout=10.0) as client:

        # --- REST-integrációt igénylő service task-ok ---

        @worker.task(task_type="create_task")
        async def create_task(alert_type: str):
            resp = await client.post("/tasks", json={"alert_type": alert_type})
            data = resp.json()
            print(f"[Task created] task_id={data['task_id']}")
            return {"task_id": data["task_id"]}

        @worker.task(task_type="lock_stock")
        async def lock_stock(alert_type: str):
            resp = await client.post("/stock/lock", json={"alert_type": alert_type})
            data = resp.json()
            print(f"[Stock locked] lock_id={data['lock_id']}")
            return {"lock_id": data["lock_id"]}

        @worker.task(task_type="allocate_technician")
        async def allocate_technician(alert_type: str):
            resp = await client.post("/technician-assignments", json={"alert_type": alert_type})
            data = resp.json()
            print(f"[Technician allocation] technician={data['technician']}")
            return {"technician": data["technician"]}

        # --- belső logikájú service task-ok, nincs REST-hívás ---

        @worker.task(task_type="schedule_task")
        async def schedule_task(alert_type: str):
            print(f"[Task scheduling] alert_type={alert_type}")
            return {"scheduled": True}

        @worker.task(task_type="analyze_error_log")
        async def analyze_error_log(alert_type: str):
            print(f"[Error log analysis] alert_type={alert_type}")
            return {"log_analyzed": True}

        # --- send task-ok (értesítések) ---

        @worker.task(task_type="notify_partner")
        async def notify_partner(alert_type: str):
            await client.post("/notifications", json={"recipient_type": "partner", "alert_type": alert_type})
            print(f"[Partner notification] alert_type={alert_type}")
            return {}

        @worker.task(task_type="notify_technician")
        async def notify_technician(alert_type: str):
            await client.post("/notifications", json={"recipient_type": "technician", "alert_type": alert_type})
            print(f"[Technician notification] alert_type={alert_type}")
            return {}

        @worker.task(task_type="notify_customerservice")
        async def notify_customerservice(alert_type: str):
            await client.post("/notifications", json={"recipient_type": "customer_service", "alert_type": alert_type})
            print(f"[Customer service notification] alert_type={alert_type}")
            return {}

        print("Worker fut, várja a jobokat... (Ctrl+C a leállításhoz)")
        await worker.work()


asyncio.run(main())
